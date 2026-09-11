import os
from datetime import date, datetime, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, text
from backend.config import settings
from backend.models import (
    Base, Candidate, Skill, Company, CompanyRequirement, DailyBatch,
    Application, Document, ApplicationDocument, Feedback, Interview, SearchAlert
)

engine = create_async_engine(settings.DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await run_migrations()

    # Check if seed data needed
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Candidate))
        candidate = result.scalars().first()
        if not candidate:
            await seed_initial_data(session)

        result = await session.execute(select(Candidate).order_by(Candidate.id).limit(1))
        default_candidate = result.scalars().first()
        if default_candidate:
            await backfill_candidate_ownership(session, default_candidate.id)


async def run_migrations():
    """Apply small, ordered SQLite migrations without requiring extra tooling.

    SQLAlchemy's ``create_all`` creates missing tables but cannot evolve tables
    already present in a user's local SQLite database.  Keep migrations here
    until the project needs a larger migration framework.
    """
    async with engine.connect() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                revision TEXT PRIMARY KEY,
                applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        applied_result = await conn.execute(text("SELECT revision FROM schema_migrations"))
        applied = {row[0] for row in applied_result}

        if "001_mvp_foundation" not in applied:
            await migrate_mvp_foundation(conn)
            await conn.execute(
                text("INSERT INTO schema_migrations (revision) VALUES (:revision)"),
                {"revision": "001_mvp_foundation"},
            )
        if "002_job_versioning" not in applied:
            await migrate_job_versioning(conn)
            await conn.execute(
                text("INSERT INTO schema_migrations (revision) VALUES (:revision)"),
                {"revision": "002_job_versioning"},
            )
        if "003_cv_document_ingestion" not in applied:
            await migrate_cv_document_ingestion(conn)
            await conn.execute(
                text("INSERT INTO schema_migrations (revision) VALUES (:revision)"),
                {"revision": "003_cv_document_ingestion"},
            )
        if "004_cv_layout_reconstruction" not in applied:
            await migrate_cv_layout_reconstruction(conn)
            await conn.execute(text("INSERT INTO schema_migrations (revision) VALUES (:revision)"), {"revision": "004_cv_layout_reconstruction"})
        await conn.commit()


async def _table_columns(conn, table_name: str) -> set[str]:
    result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
    return {row[1] for row in result}


async def _add_column_if_missing(conn, table_name: str, column_name: str, definition: str):
    if column_name not in await _table_columns(conn, table_name):
        await conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))


async def _has_candidate_batch_unique_constraint(conn) -> bool:
    indexes = await conn.execute(text("PRAGMA index_list(daily_batches)"))
    for row in indexes:
        index_name, is_unique = row[1], row[2]
        if not is_unique:
            continue
        escaped_name = str(index_name).replace('"', '""')
        index_columns = await conn.execute(text(f'PRAGMA index_info("{escaped_name}")'))
        if [index_row[2] for index_row in index_columns] == ["candidate_id", "batch_date"]:
            return True
    return False


async def _rebuild_daily_batches_for_candidate_scope(conn):
    """Replace legacy UNIQUE(batch_date) without touching application IDs."""
    existing_columns = await _table_columns(conn, "daily_batches")
    candidate_expr = "candidate_id" if "candidate_id" in existing_columns else "NULL"

    # SQLite creates foreign-key enforcement disabled by default.  Explicitly
    # disable it during this short rebuild because applications reference this
    # table; the table name remains unchanged once the swap completes.
    await conn.exec_driver_sql("PRAGMA foreign_keys = OFF")
    await conn.execute(text("""
        CREATE TABLE daily_batches_mvp_new (
            id INTEGER NOT NULL PRIMARY KEY,
            candidate_id INTEGER,
            batch_date DATE,
            day_no INTEGER NOT NULL,
            target_evaluation INTEGER,
            target_application INTEGER,
            actual_evaluation INTEGER,
            actual_application INTEGER,
            focus VARCHAR(150),
            status VARCHAR(30),
            notes TEXT,
            next_pool VARCHAR(150),
            CONSTRAINT uq_daily_batch_candidate_date UNIQUE (candidate_id, batch_date),
            FOREIGN KEY(candidate_id) REFERENCES candidates(id)
        )
    """))
    await conn.execute(text(f"""
        INSERT INTO daily_batches_mvp_new (
            id, candidate_id, batch_date, day_no, target_evaluation,
            target_application, actual_evaluation, actual_application,
            focus, status, notes, next_pool
        )
        SELECT
            id, {candidate_expr}, batch_date, day_no, target_evaluation,
            target_application, actual_evaluation, actual_application,
            focus, status, notes, next_pool
        FROM daily_batches
    """))
    await conn.execute(text("DROP TABLE daily_batches"))
    await conn.execute(text("ALTER TABLE daily_batches_mvp_new RENAME TO daily_batches"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_daily_batches_candidate_id ON daily_batches (candidate_id)"))
    await conn.exec_driver_sql("PRAGMA foreign_keys = ON")


async def migrate_mvp_foundation(conn):
    """Add MVP ownership/evaluation columns while preserving legacy data."""
    await _add_column_if_missing(conn, "applications", "job_posting_id", "INTEGER")

    for column_name, definition in (
        ("candidate_id", "INTEGER"),
        ("stored_path", "VARCHAR(500)"),
        ("raw_text", "TEXT"),
        ("structured_extraction", "TEXT"),
        ("confirmation_status", "VARCHAR(30) DEFAULT 'unconfirmed'"),
        ("extraction_error", "TEXT"),
    ):
        await _add_column_if_missing(conn, "documents", column_name, definition)

    await _add_column_if_missing(conn, "daily_batches", "candidate_id", "INTEGER")
    await _add_column_if_missing(conn, "search_alerts", "candidate_id", "INTEGER")

    if not await _has_candidate_batch_unique_constraint(conn):
        await _rebuild_daily_batches_for_candidate_scope(conn)


async def migrate_job_versioning(conn):
    """Add Job history metadata while preserving every existing Job row."""
    for column_name, definition in (
        ("normalized_source_url", "VARCHAR(500)"),
        ("source_hash", "VARCHAR(64)"),
        ("version_number", "INTEGER NOT NULL DEFAULT 1"),
        ("supersedes_job_id", "INTEGER"),
        ("version_source", "VARCHAR(30) NOT NULL DEFAULT 'imported'"),
        ("confirmed_at", "DATETIME"),
        ("last_edited_at", "DATETIME"),
    ):
        await _add_column_if_missing(conn, "jobs", column_name, definition)
    await conn.execute(text("UPDATE jobs SET version_number = 1 WHERE version_number IS NULL"))
    await conn.execute(text("UPDATE jobs SET version_source = 'imported' WHERE version_source IS NULL"))
    await conn.execute(text("UPDATE jobs SET confirmed_at = created_at WHERE confirmation_status = 'confirmed' AND confirmed_at IS NULL"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_normalized_source_url ON jobs (normalized_source_url)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_supersedes_job_id ON jobs (supersedes_job_id)"))


async def migrate_cv_document_ingestion(conn):
    """Add candidate-scoped CV hashes and confirmation metadata additively."""
    for column_name, definition in (
        ("file_hash", "VARCHAR(64)"),
        ("text_hash", "VARCHAR(64)"),
        ("extracted_at", "DATETIME"),
        ("confirmed_at", "DATETIME"),
        ("extraction_confidence", "VARCHAR(20)"),
    ):
        await _add_column_if_missing(conn, "documents", column_name, definition)
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_file_hash ON documents (file_hash)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_text_hash ON documents (text_hash)"))


async def migrate_cv_layout_reconstruction(conn):
    """Add parser provenance without reclassifying legacy Documents as layout_v2."""
    for column_name, definition in (
        ("parser_version", "VARCHAR(30)"),
        ("layout_metadata", "TEXT"),
        ("layout_confidence", "VARCHAR(20)"),
    ):
        await _add_column_if_missing(conn, "documents", column_name, definition)


async def backfill_candidate_ownership(session: AsyncSession, candidate_id: int):
    """Assign legacy single-user records to the original/default candidate.

    This is idempotent: it only fills missing ownership and does not overwrite
    records that a future candidate-selection feature has already scoped.
    """
    for table_name in ("applications", "documents", "skills", "daily_batches", "search_alerts"):
        await session.execute(
            text(f"UPDATE {table_name} SET candidate_id = :candidate_id WHERE candidate_id IS NULL"),
            {"candidate_id": candidate_id},
        )

    await session.execute(
        text("""
            INSERT OR IGNORE INTO candidate_companies (
                candidate_id, company_id, class_grade, company_eligibility,
                evidence_confidence, recommended_effort, research_status, notes,
                created_at, updated_at
            )
            SELECT
                :candidate_id, id, class_grade, company_eligibility,
                evidence_confidence, recommended_effort, research_status, notes,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM companies
        """),
        {"candidate_id": candidate_id},
    )
    await session.commit()

async def seed_initial_data(session: AsyncSession):
    # 1. Create Default Candidate
    cand = Candidate(
        profile_name="Alex Schmidt",
        degree="B.Sc. Computer Science / Software Systems",
        uni="TU Berlin",
        target="Software Engineering & AI/ML Internship",
        availability="Immediate / 6 Months Full-Time",
        location="Berlin, Germany",
        notes="Strong foundation in Python, TypeScript, algorithms, and backend systems. Eager to expand cloud infrastructure and production LLM orchestration skills."
    )
    session.add(cand)
    await session.flush()

    # 2. Add Candidate Skills Matrix
    skills = [
        Skill(candidate_id=cand.id, name="Python", category="Programming", evidence_source="GitHub Portfolio & Data Structures Course", current_level="Advanced", notes="FastAPI, Asyncio, PyTorch"),
        Skill(candidate_id=cand.id, name="TypeScript", category="Programming", evidence_source="Fullstack React Web Project", current_level="Intermediate", notes="Modern ES6+, React, Node"),
        Skill(candidate_id=cand.id, name="SQL & Relational DBs", category="Data", evidence_source="Database Engineering Module", current_level="Intermediate", notes="PostgreSQL, SQLite, SQLAlchemy"),
        Skill(candidate_id=cand.id, name="Docker & Containers", category="DevOps", evidence_source="Personal homelab & project deployment", current_level="Beginner", notes="Basic Dockerfiles and compose"),
        Skill(candidate_id=cand.id, name="German Language", category="Language", evidence_source="Goethe B2 Certificate", current_level="Intermediate", notes="Professional working proficiency B2+"),
        Skill(candidate_id=cand.id, name="English Language", category="Language", evidence_source="C1 Academic English", current_level="Expert", notes="Fluent"),
    ]
    session.add_all(skills)

    # 3. Create Documents
    doc_cv = Document(
        candidate_id=cand.id,
        name="CV_Alex_Schmidt_Tech_2026.pdf",
        doc_type="CV",
        version_date=date.today() - timedelta(days=5),
        status="active",
        owner_note="Primary tech resume highlighting Python & Fullstack projects",
        file_link="https://drive.google.com/sample/cv_tech"
    )
    doc_cl = Document(
        candidate_id=cand.id,
        name="CoverLetter_Automotive_Template_DE.pdf",
        doc_type="Cover letter",
        version_date=date.today() - timedelta(days=2),
        status="active",
        owner_note="German cover letter customized for automotive / autonomous driving",
        file_link="https://drive.google.com/sample/cl_automotive"
    )
    doc_enr = Document(
        candidate_id=cand.id,
        name="Studienbescheinigung_SS2026_TUBerlin.pdf",
        doc_type="Studienbescheinigung",
        version_date=date.today() - timedelta(days=20),
        status="active",
        owner_note="Official enrollment verification for mandatory internship",
        file_link="https://drive.google.com/sample/enrollment"
    )
    session.add_all([doc_cv, doc_cl, doc_enr])
    await session.flush()

    # 4. Companies Pool
    c1 = Company(
        name="NextDrive Robotics GmbH",
        city="Munich",
        region="Bavaria",
        webpage="https://nextdrive-robotics.example",
        technical_field="Automotive & Autonomous Systems",
        class_grade="A",
        company_eligibility="yes",
        evidence_confidence="High",
        recommended_effort="Deep",
        research_status="Evaluating",
        notes="High prestige Tier-1 supplier lab. Matches target robotics focus perfectly."
    )
    c2 = Company(
        name="QuantVibe FinTech Solutions",
        city="Frankfurt",
        region="Hesse",
        webpage="https://quantvibe.example",
        technical_field="Financial Data & Analytics",
        class_grade="B",
        company_eligibility="yes",
        evidence_confidence="Medium",
        recommended_effort="Medium+",
        research_status="Eligible",
        notes="Fast growing data analytics firm with open summer internship."
    )
    c3 = Company(
        name="CloudWave Systems AG",
        city="Berlin",
        region="Berlin",
        webpage="https://cloudwave.example",
        technical_field="Cloud Infrastructure & DevOps",
        class_grade="B-/C",
        company_eligibility="yes",
        evidence_confidence="Medium",
        recommended_effort="Medium",
        research_status="Applied",
        notes="Strong Kubernetes focus. Good candidate for initiative application."
    )
    c4 = Company(
        name="Legacy Consulting Partners",
        city="Cologne",
        region="NRW",
        webpage="https://legacy-consult.example",
        technical_field="Management Consulting",
        class_grade="D",
        company_eligibility="no",
        evidence_confidence="Low",
        recommended_effort="Light",
        research_status="Not Eligible",
        notes="Low technical engineering content; not suitable for university internship requirements."
    )
    session.add_all([c1, c2, c3, c4])
    await session.flush()

    # 5. Daily Batch (Sprint Tracking)
    today_batch = DailyBatch(
        candidate_id=cand.id,
        batch_date=date.today(),
        day_no=4,
        target_evaluation=6,
        target_application=3,
        actual_evaluation=4,
        actual_application=2,
        focus="Autonomous Systems & Robotics Focus Pool",
        status="in progress",
        notes="Targeting top Munich robotics firms today. 2 submissions completed, 1 in preparation.",
        next_pool="Berlin AI Startups Pool"
    )
    session.add(today_batch)
    await session.flush()

    # 6. Applications
    app1 = Application(
        candidate_id=cand.id,
        company_id=c1.id,
        job_id="ND-2026-INT-04",
        job_title="Intern - AI Perception & Python Backend",
        job_url="https://nextdrive-robotics.example/careers/job-04",
        application_date=date.today() - timedelta(days=3),
        daily_batch_id=today_batch.id,
        application_channel="LinkedIn Easy Apply",
        application_type="Direct",
        internship_content_eligibility="yes",
        company_class="A",
        company_recommended_effort="Deep",
        status="Interview",
        current_stage="functional department review",
        feedback_status="not applicable",
        follow_up_date=date.today() + timedelta(days=4),
        next_action="Prepare for technical perception coding interview round",
        notes="Received invite for technical interview round after CV screening!"
    )
    app2 = Application(
        candidate_id=cand.id,
        company_id=c3.id,
        job_id="CW-DEV-09",
        job_title="Junior Cloud DevOps Intern",
        job_url="https://cloudwave.example/jobs/9",
        application_date=date.today() - timedelta(days=8),
        daily_batch_id=today_batch.id,
        application_channel="Company Career Portal",
        application_type="Direct",
        internship_content_eligibility="yes",
        company_class="B-/C",
        company_recommended_effort="Medium",
        status="Rejected",
        current_stage="Recruiter review",
        feedback_status="received",
        follow_up_date=None,
        response_date=date.today() - timedelta(days=1),
        result="Rejected",
        next_action="Review feedback and practice Kubernetes / Terraform basics",
        notes="HR sent personalized rejection specifying requirement for Kubernetes multi-cluster experience."
    )
    session.add_all([app1, app2])
    await session.flush()

    # 7. Document Links
    ad1 = ApplicationDocument(application_id=app1.id, document_id=doc_cv.id, document_role="Primary CV", notes="Version 2026 with AI Perception highlight")
    ad2 = ApplicationDocument(application_id=app1.id, document_id=doc_cl.id, document_role="Tailored Cover Letter", notes="Customized with reference to autonomous sensor fusion")
    ad3 = ApplicationDocument(application_id=app2.id, document_id=doc_cv.id, document_role="Primary CV", notes="Standard Tech CV")
    session.add_all([ad1, ad2, ad3])

    # 8. Feedback & Skill Gap
    fb1 = Feedback(
        application_id=app2.id,
        company_id=c3.id,
        stage="Recruiter Review",
        feedback_date=date.today() - timedelta(days=1),
        feedback_type="Skill gap",
        raw_feedback="Dear Alex, thank you for your application. While your Python background is strong, our cloud team currently requires solid hands-on experience with Kubernetes orchestration and Terraform IaC, which was missing from your portfolio.",
        skill_gap="Kubernetes, Terraform (IaC)",
        actionable="yes",
        action_taken="Started Minikube hands-on exercises and completed beginner Terraform tutorial on local environment.",
        notes="Great feedback! HR responded politely when asked. Opportunity to re-apply in 4 months."
    )
    session.add(fb1)

    # 9. Interview
    iv1 = Interview(
        application_id=app1.id,
        company_id=c1.id,
        interview_date=datetime.now() + timedelta(days=3, hours=2),
        round_no=1,
        format="Video",
        participants="Dr. Weber (Perception Team Lead), Sarah Klein (Talent Acquisition)",
        topics="Perception pipeline, Python multiprocessing, bounding box algorithms, academic thesis overview",
        outcome="scheduled",
        follow_up="Send thank you email within 24h of interview",
        notes="Review YOLOv8 and PyTorch data loader optimization before the call."
    )
    session.add(iv1)

    # 10. Search Alert
    sa1 = SearchAlert(
        candidate_id=cand.id,
        company_id=None,
        company_name=None,
        platform="LinkedIn",
        filter_name="Robotics & AI Internships Berlin/Munich",
        country="Germany",
        join_as="Internship",
        keywords="Python, Computer Vision, Robotics, Autonomous",
        status="Active",
        last_checked=date.today(),
        last_results="14 new postings today",
        notes="Checked every morning during daily batch evaluation"
    )
    session.add(sa1)

    await session.commit()
