"""
Seed the real sales-call script ("Скрипт продающего звонка — Татьяна Балокан")
as its own metric group — the AI checks whether the manager followed this
EXACT sequence of stages, not just a generic checklist.

Creates (idempotently) a "Скрипт звонка: Татьяна Балокан" metric group in the
tutoring project, with the script's full text baked into the prompt for
grounding, and 12 ordered stage-sequence criteria.

Usage: python -m scripts.seed_script_stages
"""
import asyncio
import sys

from sqlalchemy import select

from database import AsyncSessionLocal, Project, MetricGroup, MetricGroupType, MetricItem

PROJECT_NAME = "Репетиторы: продающие созвоны"
GROUP_NAME = "Скрипт звонка: Татьяна Балокан"

PROMPT_TEMPLATE = """\
Ты проверяешь, следовал ли менеджер ПОСЛЕДОВАТЕЛЬНОСТИ этапов конкретного
скрипта продающего звонка (не общим рекомендациям, а именно этой структуре).

Оригинальный скрипт для сверки:

--- Приветствие & знакомство ---
Менеджер здоровается, представляется помощницей Татьяны Балокан, рассказывает
пару фактов о себе для сближения, предлагает перейти на «ты», просит клиента
рассказать о себе. Затем обозначает план звонка: сначала вопросы о текущей
ситуации в преподавании, потом ответы на вопросы клиента, затем — если формат
подходит — условия. Явно предупреждает, что будет задавать личные вопросы
(доход, ученики, время) и просит согласие. Договаривается не расходиться
«подумать» — предлагает клиенту сразу задавать любые вопросы. Спрашивает:
готовность от 1 до 10 стать востребованным репетитором + сколько времени есть
под учеников.

--- Выявление потребностей ---
Проговаривает то, что уже известно о клиенте (предмет, статус, чек, кол-во
учеников). Спрашивает про интенсив: что понравилось, чего не хватило, что уже
пробовал(а) применять, почему решил(а) прийти именно сейчас.

--- Точка А и точка Б ---
Задаёт вопросы про текущую ситуацию (точка А), подобранные под сегмент клиента
(начинающий / практикующий / продвинутый репетитор — про каналы привлечения,
стоимость занятий, группы, стабильность потока и т.д.), и про желаемый
результат через год (точка Б) — как изменится жизнь, какой доход, какие сферы
подтянутся, какой идеальный результат обучения.

--- Резюмирование ---
Кратко резюмирует точку А (боли) и точку Б (желания/цели) клиенту, уточняет,
всё ли верно понял. Благодарит за открытость.

--- Презентация продукта ---
Рассказывает про программу «Современный репетитор» (5 недель, модули:
определение себя как репетитора → создание интересных уроков →
ценообразование → привлечение учеников и продажи → система и масштабирование
→ бонус про соцсети), явно связывая результат каждого модуля с болью/целью,
которую клиент назвал ранее.

--- Обработка "спасибо, но не куплю" ---
Если клиент благодарит, но не покупает — не сдаётся сразу: говорит, что был бы
рад видеть результат клиента, предлагает уточнить настоящую причину сомнений
(цена или неуверенность в результате), предлагает обсудить скидку.

Оцени по каждому пункту чек-листа, следовал ли менеджер этой последовательности
в РЕАЛЬНОМ разговоре:
{items}

Шкала: 1 — выполнено полноценно; 0.5 — частично/скомкано; 0 — не выполнено.

Транскрибация разговора:
{transcription}
"""

CRITERIA = [
    "Поприветствовал, представился как помощница Татьяны Балокан",
    "Перешёл на «ты» и узнал информацию о клиенте (сближение)",
    "Обозначил план звонка (вопросы → ответы → условия)",
    "Получил согласие задавать личные вопросы (доход, ученики, время)",
    "Задал вопрос про готовность (1–10) и время на учеников",
    "Выявил обратную связь по интенсиву (понравилось / не хватило / применял)",
    "Узнал точку А — текущую ситуацию по сегменту клиента",
    "Узнал точку Б — желаемый результат через год",
    "Резюмировал точку А и Б и получил подтверждение клиента",
    "Презентовал программу, связав модули с болью/целью клиента",
    "Отработал «спасибо, но не куплю» / возражение по цене",
    "Подвёл к следующему шагу / закрытию",
]


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        project = (await db.execute(
            select(Project).where(Project.name == PROJECT_NAME)
        )).scalar_one_or_none()
        if project is None:
            print(f"Error: project {PROJECT_NAME!r} not found. Run seed_tutoring first.")
            sys.exit(1)

        group = (await db.execute(
            select(MetricGroup).where(
                MetricGroup.project_id == project.id, MetricGroup.name == GROUP_NAME
            )
        )).scalar_one_or_none()
        if group is None:
            group = MetricGroup(
                project_id=project.id,
                name=GROUP_NAME,
                group_type=MetricGroupType.SCRIPT_STAGES,
                prompt_template=PROMPT_TEMPLATE,
            )
            db.add(group)
            await db.flush()
            print(f"Created metric group id={group.id} name={GROUP_NAME!r}")
        else:
            group.prompt_template = PROMPT_TEMPLATE
            print(f"Updated metric group id={group.id} name={GROUP_NAME!r}")

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

        await db.commit()
        print(f"Done: {len(CRITERIA)} script-stage criteria seeded.")


if __name__ == "__main__":
    asyncio.run(seed())
