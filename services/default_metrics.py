"""
Universal metric group applied to every project automatically — not tied to
any one project's niche. Covers the 8 stages of a sales meeting ("Этапы
продающей встречи"): rapport → programming → point A → point B → summary →
product presentation → objection handling → closing.

ensure_default_metric_group() is idempotent (create-or-update, matching the
pattern used by scripts/seed_*.py) and is called from two places:
  - api/routes/projects.py: create_project, so every NEW project gets it.
  - scripts/backfill_default_metrics.py: applied once to EXISTING projects.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import MetricGroup, MetricGroupType, MetricItem

GROUP_NAME = "Этапы продающей встречи"

PROMPT_TEMPLATE = """\
Ты проверяешь, провёл ли менеджер звонок по универсальной структуре
продающей встречи — 8 этапов, в этом порядке:

1. Знакомство и установление контакта — познакомился с клиентом, нашёл точки
   соприкосновения, создал доверительную атмосферу.
2. Программирование — объяснил клиенту, что его ждёт дальше по ходу встречи,
   и установил правила (например, договорился о честности, о вопросах).
3. Точка А — вкопался в текущую ситуацию клиента: сфера деятельности, доход,
   обстановка, боли, опыт.
4. Точка Б — погрузил клиента в желаемую точку: доход, цели и мечты,
   окружение.
5. Резюмирование — подвёл итоги точек А и Б, мягко указал на несоответствие
   текущего положения желаемому.
6. Презентация продукта — презентовал продукт исходя из болей клиента: чем
   поможет, как изменит жизнь, какой даст путь к результатам.
7. Отработка возражений — помог клиенту справиться с сомнениями и
   переживаниями, подвёл к финальному шагу (оплате).
8. Закрытие сделки — помог клиенту оплатить удобным ему способом (рассрочка,
   перевод, ВР, кредит).

Оцени по каждому пункту, выполнил ли менеджер этот этап в разговоре:
{items}

Шкала: 1 — выполнено полноценно; 0.5 — частично/скомкано; 0 — не выполнено.

Транскрибация разговора:
{transcription}
"""

CRITERIA = [
    "Знакомство и установление контакта",
    "Программирование (что ждёт дальше + правила встречи)",
    "Точка А — текущая ситуация клиента",
    "Точка Б — желаемая ситуация клиента",
    "Резюмирование точек А и Б",
    "Презентация продукта через боли клиента",
    "Отработка возражений",
    "Закрытие сделки / способ оплаты",
]


async def ensure_default_metric_group(db: AsyncSession, project_id: int) -> MetricGroup:
    """Create-or-update the universal 8-stage group for one project. Caller is
    responsible for flush/commit."""
    group = (await db.execute(
        select(MetricGroup).where(
            MetricGroup.project_id == project_id, MetricGroup.name == GROUP_NAME
        )
    )).scalar_one_or_none()

    if group is None:
        group = MetricGroup(
            project_id=project_id,
            name=GROUP_NAME,
            group_type=MetricGroupType.SCRIPT_STAGES,
            prompt_template=PROMPT_TEMPLATE,
        )
        db.add(group)
        await db.flush()
    else:
        group.prompt_template = PROMPT_TEMPLATE

    existing = {
        item.position: item
        for item in (await db.execute(
            select(MetricItem).where(MetricItem.metric_group_id == group.id)
        )).scalars()
    }
    for idx, name in enumerate(CRITERIA, start=1):
        item = existing.get(idx)
        if item is None:
            db.add(MetricItem(metric_group_id=group.id, position=idx, name=name, is_active=True))
        else:
            item.name = name
            item.is_active = True
    for pos, item in existing.items():
        if pos > len(CRITERIA):
            item.is_active = False

    return group
