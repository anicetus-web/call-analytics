"""
LLM-based call analysis service.

For each metric_group of the project:
  1. Build a prompt from the group's prompt_template + numbered metric_items
  2. Send to LLM API
  3. Parse the response: "1-1;2-0;3-0.5" or "1-1-45.2;2-0;3-0.5-120.5"
  4. Return structured results

Response format per item: {position}-{score}[-{timecode}]
  score: 0 | 0.5 | 1
  timecode (optional): seconds as float, only when score > 0

Raises AnalysisError if all retries fail for a given group (other groups continue).
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal

from openai import AsyncOpenAI, APIError, APITimeoutError, RateLimitError

from config import settings
from services.quota import QuotaExhaustedError

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

# Matches one item token bounded by start/`;`/whitespace on the left and `;`/whitespace/end
# on the right, so glued numbers like "1-15" don't yield a spurious "1-1" + leftover "5".
# Token: {position}-{score}[-{timecode}]
_ITEM_PATTERN = re.compile(
    r"(?:^|[;\s])(\d+)-(0\.5|0|1)(?:-(\d+(?:\.\d+)?))?(?=$|[;\s])"
)

VALID_SCORES = {Decimal("0"), Decimal("0.5"), Decimal("1")}


class AnalysisError(Exception):
    """Raised when LLM analysis fails for a metric group after all retries."""


@dataclass
class ItemResult:
    position: int
    metric_item_id: int
    score: Decimal
    timecode_start: Decimal | None = None


@dataclass
class GroupResult:
    metric_group_id: int
    items: list[ItemResult] = field(default_factory=list)
    raw_response: str = ""       # full LLM response for this group (for debugging)
    error: str | None = None     # set if this group failed after retries


def _build_prompt(template: str, items: list, transcription: str) -> str:
    """
    Substitute {items} and {transcription} placeholders in the template.
    items: list of MetricItem ORM objects, ordered by position.
    """
    numbered = "\n".join(f"{item.position}) {item.name}" for item in items)
    return (
        template
        .replace("{items}", numbered)
        .replace("{transcription}", transcription)
    )


def _parse_response(raw: str, items: list) -> list[ItemResult]:
    """
    Parse LLM response string into ItemResult list.
    items: ordered list of MetricItem (used to map position → metric_item_id).

    Accepts both formats:
      "1-1;2-0;3-0.5"
      "1-1-45.2;2-0;3-0.5-120.5"

    Unknown positions and invalid scores are silently skipped (logged as warnings).
    Duplicate positions (the LLM repeating an item number) keep only the first
    occurrence — AnalysisResult has a unique (call_id, metric_item_id) constraint,
    so letting both through would crash the whole call's DB insert over one
    hallucinated duplicate instead of just that group's redundant token.
    """
    position_to_item = {item.position: item for item in items}
    results: list[ItemResult] = []
    seen_positions: set[int] = set()

    for match in _ITEM_PATTERN.finditer(raw):
        position = int(match.group(1))
        score = Decimal(match.group(2))
        timecode_str = match.group(3)

        if position not in position_to_item:
            logger.warning("LLM returned unknown position %d, skipping", position)
            continue

        if score not in VALID_SCORES:
            logger.warning("LLM returned invalid score %s for position %d, skipping", score, position)
            continue

        if position in seen_positions:
            logger.warning("LLM returned duplicate position %d, keeping first occurrence", position)
            continue
        seen_positions.add(position)

        timecode: Decimal | None = None
        if timecode_str is not None and score > 0:
            timecode = Decimal(timecode_str)

        results.append(ItemResult(
            position=position,
            metric_item_id=position_to_item[position].id,
            score=score,
            timecode_start=timecode,
        ))

    return results


async def _call_llm(prompt: str) -> str:
    """
    Send a single prompt to the LLM and return the raw text response.
    Raises QuotaExhaustedError or AnalysisError on failure.
    """
    last_exc: Exception | None = None

    for attempt in range(1, settings.MAX_RETRY_ATTEMPTS + 1):
        try:
            response = await _client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты — аналитик звонков. Отвечай ТОЛЬКО строкой вида "
                            "'N-S' или 'N-S-T', разделённой ';' между пунктами, где "
                            "N — номер пункта, S — оценка (0, 0.5 или 1), "
                            "T — необязательный таймкод в секундах (только при S>0). "
                            "Пример: '1-1-45.2;2-0;3-0.5'. Никаких пояснений и Markdown."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=settings.LLM_TEMPERATURE,
                max_tokens=settings.LLM_MAX_TOKENS,
            )
            return (response.choices[0].message.content or "").strip()

        except (APITimeoutError, APIError) as exc:
            last_exc = exc
            if attempt < settings.MAX_RETRY_ATTEMPTS:
                delay = settings.RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "LLM API error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt, settings.MAX_RETRY_ATTEMPTS, delay, exc,
                )
                await asyncio.sleep(delay)

        except RateLimitError as exc:
            if getattr(exc, "code", None) == "insufficient_quota":
                raise QuotaExhaustedError("OpenAI quota exhausted") from exc
            last_exc = exc
            if attempt < settings.MAX_RETRY_ATTEMPTS:
                delay = settings.RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
                logger.warning("LLM rate limit hit (attempt %d/%d), waiting %.1fs",
                               attempt, settings.MAX_RETRY_ATTEMPTS, delay)
                await asyncio.sleep(delay)

    raise AnalysisError(
        f"LLM failed after {settings.MAX_RETRY_ATTEMPTS} attempts: {last_exc}"
    )


async def analyze_call(
    transcription: str,
    metric_groups: list,  # list of MetricGroup ORM objects (with .items loaded)
) -> list[GroupResult]:
    """
    Analyze a call transcription against all metric groups.

    Returns one GroupResult per group.
    If a group fails after retries, its GroupResult.error is set and processing continues.
    Raises QuotaExhaustedError immediately if quota is exhausted (caller should halt queue).
    """
    results: list[GroupResult] = []

    for group in metric_groups:
        active_items = [item for item in group.items if item.is_active]
        if not active_items:
            logger.info("Metric group %d has no active items, skipping", group.id)
            results.append(GroupResult(metric_group_id=group.id))
            continue

        prompt = _build_prompt(group.prompt_template, active_items, transcription)

        raw: str | None = None
        parsed: list[ItemResult] = []
        error: str | None = None

        # Up to 2 parse retries (LLM returned garbage format, or scored only some items)
        for parse_attempt in range(1, 3):
            try:
                raw = await _call_llm(prompt)  # may raise QuotaExhaustedError
                parsed = _parse_response(raw, active_items)

                if len(parsed) < len(active_items):
                    logger.warning(
                        "Group %d: LLM scored %d/%d items (attempt %d): %r",
                        group.id, len(parsed), len(active_items), parse_attempt, raw,
                    )
                    if parse_attempt == 2:
                        # Keep whatever we did get — better than discarding a mostly-
                        # complete response — but flag it so has_partial_error surfaces.
                        error = (
                            f"LLM scored only {len(parsed)}/{len(active_items)} items "
                            f"after retry: {raw!r}"
                        )
                    continue

                break  # success — every active item was scored

            except AnalysisError as exc:
                error = str(exc)
                break  # no more retries for this group

        results.append(GroupResult(
            metric_group_id=group.id,
            items=parsed,
            raw_response=raw or "",
            error=error,
        ))

        logger.info(
            "Group %d: %d/%d items scored%s",
            group.id,
            len(parsed),
            len(active_items),
            f" | error: {error}" if error else "",
        )

    return results
