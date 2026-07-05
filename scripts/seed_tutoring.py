"""
Seed the real "tutoring sales call" evaluation setup for the customer's
educational program ("Доход от 100 000 ₽ для репетиторов").

Creates (idempotently):
  - a project for the program,
  - one metric group "Оценка продающего созвона" whose prompt_template carries
    the product knowledge base (so the LLM judges the call in the product's
    context), and
  - the 13 evaluation criteria the customer specified, as ordered metric items.

Re-running updates the group's prompt and the item names in place instead of
duplicating anything.

Usage (inside the api/worker container, or any env with DATABASE_URL set):
    python -m scripts.seed_tutoring
    python -m scripts.seed_tutoring --project "Репетиторы"
    python -m scripts.seed_tutoring --purge-stub-calls    # also delete stub_demo_% calls

--purge-stub-calls is destructive (removes the demo/stub calls and their
transcriptions/analysis results via CASCADE) and is off by default.
"""
import argparse
import asyncio
import sys

from sqlalchemy import select

from database import (
    AsyncSessionLocal, Project, MetricGroup, MetricGroupType, MetricItem, User, UserRole, Call,
)

GROUP_NAME = "Оценка продающего созвона"

# Product knowledge base baked into the prompt so each criterion is judged in
# the context of THIS product, not generic sales. {items} and {transcription}
# are substituted by services/analyzer.py at scoring time.
PROMPT_TEMPLATE = """\
Ты оцениваешь продающий телефонный созвон менеджера образовательной программы
для репетиторов «Стабильный доход от 100 000 ₽ в месяц».

О продукте (контекст для оценки):
— Продукт: 2-месячная программа, которая помогает репетитору выйти на стабильный
  доход от 100 000 ₽/мес — выбор ниши, упаковка эксперта, интересные уроки,
  продажи, маркетинг и построение потока учеников.
— Аудитория: действующие учителя и репетиторы, а также те, кто хочет начать
  преподавать (студенты, специалисты).
— Типичные боли клиента: мало учеников, нестабильный доход, не знает где искать
  клиентов, боится продавать, не умеет поднимать стоимость занятий, не выделяется
  среди конкурентов, нет стратегии развития.
— Тарифы: «Базовый» 29 990 ₽ (платформа, все уроки, домашние задания, сертификат);
  «Стандарт» 79 990 ₽ (+ кураторы, проверка ДЗ, общий чат, помощь с портфолио,
  еженедельные созвоны); «Мастер-группа» 119 990 ₽ (+ личные созвоны с автором и
  методологом, индивидуальная стратегия, персональная обратная связь). Доступны
  полная оплата и рассрочка.

Оцени, насколько менеджер выполнил каждый пункт чек-листа в этом разговоре:
{items}

Шкала оценки каждого пункта:
  1   — выполнено полноценно;
  0.5 — выполнено частично или поверхностно;
  0   — не выполнено.

Транскрибация разговора:
{transcription}
"""

# The 13 criteria from the customer brief, in order.
CRITERIA = [
    "Выявил текущую ситуацию клиента",
    "Узнал опыт клиента в репетиторстве",
    "Узнал текущий уровень дохода",
    "Узнал желаемый уровень дохода",
    "Выявил основные боли клиента",
    "Выявил мотивацию покупки",
    "Связал презентацию курса с потребностями клиента",
    "Подобрал подходящий тариф",
    "Объяснил преимущества выбранного тарифа",
    "Отработал возражения клиента",
    "Подвёл клиента к принятию решения",
    "Предложил оплату или рассрочку",
    "Зафиксировал следующий шаг после созвона",
]


async def seed(project_name: str, purge_stub_calls: bool) -> None:
    async with AsyncSessionLocal() as db:
        # Resolve an admin to own the project (created_by is required).
        admin = (await db.execute(
            select(User).where(User.role == UserRole.ADMIN).order_by(User.id).limit(1)
        )).scalar_one_or_none()
        if admin is None:
            print("Error: no admin user found. Run scripts.create_admin first.")
            sys.exit(1)

        # Project — find or create.
        project = (await db.execute(
            select(Project).where(Project.name == project_name)
        )).scalar_one_or_none()
        if project is None:
            project = Project(
                name=project_name,
                description="Продающие созвоны образовательной программы для репетиторов.",
                created_by=admin.id,
            )
            db.add(project)
            await db.flush()
            print(f"Created project id={project.id} name={project_name!r}")
        else:
            print(f"Using existing project id={project.id} name={project_name!r}")

        # Metric group — find or create, always refresh the prompt template.
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

        # Items — upsert by position, reactivating any that were archived.
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
        # Archive any leftover items beyond our 13 (soft-delete keeps history).
        for pos, item in existing.items():
            if pos > len(CRITERIA):
                item.is_active = False

        if purge_stub_calls:
            stub = (await db.execute(
                select(Call).where(Call.original_filename.like("stub_demo_%"))
            )).scalars().all()
            for call in stub:
                await db.delete(call)
            print(f"Deleted {len(stub)} stub_demo_% call(s) and their cascade data")

        await db.commit()
        print(f"Done: {len(CRITERIA)} criteria seeded for group {GROUP_NAME!r}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed tutoring sales-call evaluation criteria.")
    parser.add_argument("--project", default="Репетиторы: продающие созвоны",
                        help="Project name to create/use.")
    parser.add_argument("--purge-stub-calls", action="store_true",
                        help="Also delete demo calls whose filename starts with stub_demo_ (destructive).")
    args = parser.parse_args()
    asyncio.run(seed(args.project, args.purge_stub_calls))
