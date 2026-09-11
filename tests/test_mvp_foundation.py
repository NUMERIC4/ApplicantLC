from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.database import AsyncSessionLocal, init_db
from backend.models import (
    Application,
    ApplicationDocument,
    Candidate,
    CandidateCompany,
    Company,
    DailyBatch,
    Document,
    Evaluation,
    EvaluationRequirement,
    Job,
    JobRequirement,
)


@pytest.mark.asyncio
async def test_mvp_foundation_supports_independent_candidate_records():
    """The new relations preserve independent historical CV/job evaluations."""
    await init_db()

    async with AsyncSessionLocal() as session:
        candidate_a = Candidate(profile_name="Foundation Candidate A")
        candidate_b = Candidate(profile_name="Foundation Candidate B")
        company = Company(name="Foundation Systems GmbH")
        session.add_all([candidate_a, candidate_b, company])
        await session.flush()

        assessment_a = CandidateCompany(
            candidate_id=candidate_a.id,
            company_id=company.id,
            class_grade="A",
            recommended_effort="Deep",
        )
        assessment_b = CandidateCompany(
            candidate_id=candidate_b.id,
            company_id=company.id,
            class_grade="C",
            recommended_effort="Light",
        )
        shared_date = date(2099, 1, 1)
        batch_a = DailyBatch(candidate_id=candidate_a.id, batch_date=shared_date, day_no=1)
        batch_b = DailyBatch(candidate_id=candidate_b.id, batch_date=shared_date, day_no=1)

        cv_a = Document(candidate_id=candidate_a.id, name="CV A", doc_type="CV")
        cv_b = Document(candidate_id=candidate_a.id, name="CV B", doc_type="CV")
        candidate_b_document = Document(candidate_id=candidate_b.id, name="Candidate B CV", doc_type="CV")
        job = Job(
            company_id=company.id,
            title="Backend Engineering Intern",
            confirmation_status="confirmed",
        )
        session.add_all([assessment_a, assessment_b, batch_a, batch_b, cv_a, cv_b, candidate_b_document, job])
        await session.flush()

        requirement = JobRequirement(
            job_id=job.id,
            requirement="Python and SQL",
            category="Technical",
            importance="High",
            source_text="Required qualifications",
        )
        application = Application(
            candidate_id=candidate_a.id,
            company_id=company.id,
            job_posting_id=job.id,
            job_title=job.title,
            daily_batch_id=batch_a.id,
        )
        session.add_all([requirement, application])
        await session.flush()

        application_document = ApplicationDocument(
            application_id=application.id,
            document_id=cv_a.id,
            document_role="Primary CV",
        )
        evaluation_a = Evaluation(
            candidate_id=candidate_a.id,
            document_id=cv_a.id,
            job_id=job.id,
            overall_score=84,
            requirement_coverage=80,
            confidence="high",
            summary="CV A is a strong match.",
        )
        evaluation_b = Evaluation(
            candidate_id=candidate_a.id,
            document_id=cv_b.id,
            job_id=job.id,
            overall_score=72,
            requirement_coverage=65,
            confidence="medium",
            summary="CV B is a partial match.",
        )
        session.add_all([application_document, evaluation_a, evaluation_b])
        await session.flush()

        requirement_result = EvaluationRequirement(
            evaluation_id=evaluation_a.id,
            job_requirement_id=requirement.id,
            requirement_text=requirement.requirement,
            importance=requirement.importance,
            fit="strong",
            cv_evidence="Python and SQL projects listed in CV A.",
            reason="Directly supported by the selected CV.",
        )
        session.add(requirement_result)
        await session.commit()

        assessments = (await session.execute(
            select(CandidateCompany).where(CandidateCompany.company_id == company.id)
        )).scalars().all()
        assert candidate_a.id != candidate_b.id
        assert {assessment.class_grade for assessment in assessments} == {"A", "C"}

        same_day_batches = (await session.execute(
            select(DailyBatch).where(DailyBatch.batch_date == shared_date)
        )).scalars().all()
        assert {batch.candidate_id for batch in same_day_batches} >= {candidate_a.id, candidate_b.id}

        stored_documents = (await session.execute(
            select(Document).where(Document.id.in_([cv_a.id, cv_b.id, candidate_b_document.id]))
        )).scalars().all()
        assert {document.candidate_id for document in stored_documents} == {candidate_a.id, candidate_b.id}

        stored_requirements = (await session.execute(
            select(JobRequirement).where(JobRequirement.job_id == job.id)
        )).scalars().all()
        stored_job = (await session.execute(select(Job).where(Job.id == job.id))).scalars().one()
        assert stored_job.company_id == company.id
        assert [item.requirement for item in stored_requirements] == ["Python and SQL"]

        stored_evaluations = (await session.execute(
            select(Evaluation).where(Evaluation.job_id == job.id)
        )).scalars().all()
        assert {evaluation.document_id for evaluation in stored_evaluations} == {cv_a.id, cv_b.id}
        assert len(stored_evaluations) == 2

        stored_result = (await session.execute(
            select(EvaluationRequirement).where(EvaluationRequirement.evaluation_id == evaluation_a.id)
        )).scalars().one()
        assert stored_result.requirement_text == "Python and SQL"

        preserved_link = (await session.execute(
            select(ApplicationDocument).where(ApplicationDocument.application_id == application.id)
        )).scalars().one()
        assert preserved_link.document_id == cv_a.id


@pytest.mark.asyncio
async def test_candidate_company_unique_constraint_and_init_are_idempotent():
    await init_db()
    await init_db()

    async with AsyncSessionLocal() as session:
        candidate = Candidate(profile_name="Uniqueness Candidate")
        company = Company(name="Uniqueness Company")
        session.add_all([candidate, company])
        await session.flush()

        session.add(CandidateCompany(candidate_id=candidate.id, company_id=company.id))
        await session.commit()

        session.add(CandidateCompany(candidate_id=candidate.id, company_id=company.id))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
