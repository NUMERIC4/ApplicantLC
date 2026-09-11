from datetime import datetime, date
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, Text, Date, DateTime, ForeignKey, Float, Boolean,
    Table, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True, index=True)
    profile_name = Column(String(100), nullable=False)
    degree = Column(String(150), nullable=True)
    uni = Column(String(150), nullable=True)
    target = Column(String(200), nullable=True) # e.g. Software Engineering Intern / Data Scientist
    availability = Column(String(100), nullable=True) # e.g. Immediate / Summer 2026 / 6 Months
    location = Column(String(150), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    skills = relationship("Skill", back_populates="candidate", cascade="all, delete-orphan")
    applications = relationship("Application", back_populates="candidate")
    documents = relationship("Document", back_populates="candidate")
    daily_batches = relationship("DailyBatch", back_populates="candidate")
    search_alerts = relationship("SearchAlert", back_populates="candidate")
    company_assessments = relationship("CandidateCompany", back_populates="candidate", cascade="all, delete-orphan")
    evaluations = relationship("Evaluation", back_populates="candidate", cascade="all, delete-orphan")


class Skill(Base):
    __tablename__ = "skills"

    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=True)
    name = Column(String(100), nullable=False, index=True)
    category = Column(String(100), nullable=True) # e.g. Programming, Framework, Cloud, Language, Soft Skill
    evidence_source = Column(String(255), nullable=True) # GitHub repo, Course Certificate, Thesis, Project
    current_level = Column(String(50), default="Beginner") # Beginner, Intermediate, Advanced, Expert
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    candidate = relationship("Candidate", back_populates="skills")


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, index=True)
    city = Column(String(100), nullable=True)
    region = Column(String(100), nullable=True)
    webpage = Column(String(255), nullable=True)
    technical_field = Column(String(150), nullable=True) # e.g. Automotive, AI/Robotics, FinTech, Embedded
    class_grade = Column(String(10), default="B") # A, B, B-/C, C, D
    company_eligibility = Column(String(20), default="yes") # yes, no, unclear
    evidence_confidence = Column(String(50), default="High") # High, Medium, Low, 0-100%
    recommended_effort = Column(String(30), default="Medium") # Deep, Medium+, Medium, Light, Standard
    research_status = Column(String(50), default="Evaluating") # Pending, Evaluating, Eligible, Not Eligible, Unclear, Applied, Alert Active, Not Suitable
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    applications = relationship("Application", back_populates="company")
    requirements = relationship("CompanyRequirement", back_populates="company", cascade="all, delete-orphan")
    feedbacks = relationship("Feedback", back_populates="company")
    interviews = relationship("Interview", back_populates="company")
    search_alerts = relationship("SearchAlert", back_populates="company")
    candidate_assessments = relationship("CandidateCompany", back_populates="company", cascade="all, delete-orphan")
    jobs = relationship("Job", back_populates="company", cascade="all, delete-orphan")


class CandidateCompany(Base):
    """Candidate-specific assessment of a reusable company record."""
    __tablename__ = "candidate_companies"
    __table_args__ = (
        UniqueConstraint("candidate_id", "company_id", name="uq_candidate_company"),
    )

    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    class_grade = Column(String(10), default="B")
    company_eligibility = Column(String(20), default="yes")
    evidence_confidence = Column(String(50), default="High")
    recommended_effort = Column(String(30), default="Medium")
    # Transitional snapshot of the legacy Company.research_status.  It remains
    # unconstrained because future research facts may be independently true.
    research_status = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    candidate = relationship("Candidate", back_populates="company_assessments")
    company = relationship("Company", back_populates="candidate_assessments")


class Job(Base):
    """A job posting is distinct from an application to that posting."""
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    title = Column(String(300), nullable=False)
    source_url = Column(String(500), nullable=True)
    normalized_source_url = Column(String(500), nullable=True, index=True)
    source_hash = Column(String(64), nullable=True, index=True)
    description = Column(Text, nullable=True)
    location = Column(String(200), nullable=True)
    source_platform = Column(String(100), nullable=True)
    raw_source_text = Column(Text, nullable=True)
    structured_extraction = Column(Text, nullable=True)
    confirmation_status = Column(String(30), nullable=False, default="draft")
    version_number = Column(Integer, nullable=False, default=1)
    supersedes_job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    version_source = Column(String(30), nullable=False, default="imported")
    confirmed_at = Column(DateTime, nullable=True)
    last_edited_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship("Company", back_populates="jobs")
    requirements = relationship("JobRequirement", back_populates="job", cascade="all, delete-orphan")
    applications = relationship("Application", back_populates="job_posting")
    evaluations = relationship("Evaluation", back_populates="job")
    supersedes_job = relationship("Job", remote_side=[id], foreign_keys=[supersedes_job_id])


class JobRequirement(Base):
    __tablename__ = "job_requirements"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    requirement = Column(Text, nullable=False)
    category = Column(String(100), nullable=True)
    importance = Column(String(20), nullable=True)
    source_text = Column(Text, nullable=True)

    job = relationship("Job", back_populates="requirements")
    evaluation_requirements = relationship("EvaluationRequirement", back_populates="job_requirement")


class CompanyRequirement(Base):
    __tablename__ = "company_requirements"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True)
    requirement = Column(Text, nullable=False) # e.g. Python, Docker, Fluent German C1
    category = Column(String(100), nullable=True) # Technical, Soft, Language, Degree, Visa
    importance = Column(String(20), default="Medium") # High, Medium, Low
    user_evidence = Column(Text, nullable=True)
    fit = Column(String(20), default="partial") # strong, good, partial, gap, unknown
    gap_action = Column(Text, nullable=True)
    source_url = Column(String(255), nullable=True)

    company = relationship("Company", back_populates="requirements")
    application = relationship("Application", back_populates="requirements")


class DailyBatch(Base):
    __tablename__ = "daily_batches"
    __table_args__ = (
        UniqueConstraint("candidate_id", "batch_date", name="uq_daily_batch_candidate_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=True, index=True)
    batch_date = Column(Date, default=date.today, index=True)
    day_no = Column(Integer, nullable=False, default=1) # Day count from procedure launch
    target_evaluation = Column(Integer, default=5) # Daily goal of companies/postings to inspect
    target_application = Column(Integer, default=3) # Daily limit/target of applications submitted
    actual_evaluation = Column(Integer, default=0)
    actual_application = Column(Integer, default=0)
    focus = Column(String(150), nullable=True) # Target sector/batch (e.g. AI Startups Berlin)
    status = Column(String(30), default="in progress") # planned, in progress, completed, blocked, skipped
    notes = Column(Text, nullable=True)
    next_pool = Column(String(150), nullable=True)

    applications = relationship("Application", back_populates="daily_batch")
    candidate = relationship("Candidate", back_populates="daily_batches")


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    job_id = Column(String(100), nullable=True)
    # Legacy job_id remains an external requisition/reference string.  New
    # workflow records link to the first-class Job entity below.
    job_posting_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    job_title = Column(String(200), nullable=False)
    job_url = Column(String(500), nullable=True)
    application_date = Column(Date, default=date.today)
    daily_batch_id = Column(Integer, ForeignKey("daily_batches.id"), nullable=True)
    application_channel = Column(String(100), nullable=True) # LinkedIn, StepStone, Direct Career Page, Email, Xing
    application_type = Column(String(50), default="Direct") # Direct, Initiative, Referral, Portal, Agency
    internship_content_eligibility = Column(String(50), default="yes") # yes, no, partial, compulsory
    company_class = Column(String(10), default="B") # snapshot or override
    company_recommended_effort = Column(String(30), default="Medium")
    status = Column(String(30), default="Preparing") # not started, Preparing, Ready, Applied, Response, Interview, Rejected, offer, Withdrawn
    current_stage = Column(String(50), default="Portal submitted") # Portal submitted, Recruiter review, functional department review, Interview, Offer, closed, Submitted
    feedback_status = Column(String(30), default="not yet") # not yet, requested, received, no response, not applicable
    follow_up_date = Column(Date, nullable=True)
    response_date = Column(Date, nullable=True)
    result = Column(String(50), nullable=True) # Offer, Rejection, Ghosted, Withdrawn
    next_action = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True) # Backlog, audit trail, timeline logs

    # Relationships
    candidate = relationship("Candidate", back_populates="applications")
    company = relationship("Company", back_populates="applications")
    job_posting = relationship("Job", back_populates="applications")
    daily_batch = relationship("DailyBatch", back_populates="applications")
    requirements = relationship("CompanyRequirement", back_populates="application")
    application_documents = relationship("ApplicationDocument", back_populates="application", cascade="all, delete-orphan")
    feedbacks = relationship("Feedback", back_populates="application", cascade="all, delete-orphan")
    interviews = relationship("Interview", back_populates="application", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=True, index=True)
    name = Column(String(200), nullable=False)
    doc_type = Column(String(50), default="CV") # CV, Cover letter, Studienbescheinigung, Transcript, Certificate, Other
    version_date = Column(Date, default=date.today)
    status = Column(String(30), default="active") # active, archived, deprecated
    owner_note = Column(Text, nullable=True)
    file_link = Column(String(500), nullable=True)
    stored_path = Column(String(500), nullable=True)
    raw_text = Column(Text, nullable=True)
    structured_extraction = Column(Text, nullable=True)
    confirmation_status = Column(String(30), nullable=False, default="unconfirmed")
    extraction_error = Column(Text, nullable=True)
    file_hash = Column(String(64), nullable=True, index=True)
    text_hash = Column(String(64), nullable=True, index=True)
    extracted_at = Column(DateTime, nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    extraction_confidence = Column(String(20), nullable=True)
    parser_version = Column(String(30), nullable=True)
    layout_metadata = Column(Text, nullable=True)
    layout_confidence = Column(String(20), nullable=True)

    candidate = relationship("Candidate", back_populates="documents")
    application_links = relationship("ApplicationDocument", back_populates="document", cascade="all, delete-orphan")


class Evaluation(Base):
    """Immutable historical comparison of one confirmed CV and one Job."""
    __tablename__ = "evaluations"

    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    overall_score = Column(Float, nullable=True)
    requirement_coverage = Column(Float, nullable=True)
    confidence = Column(String(20), nullable=True)
    summary = Column(Text, nullable=True)
    structured_result = Column(Text, nullable=True)
    raw_model_result = Column(Text, nullable=True)
    model_identifier = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    candidate = relationship("Candidate", back_populates="evaluations")
    document = relationship("Document")
    job = relationship("Job", back_populates="evaluations")
    requirement_results = relationship("EvaluationRequirement", back_populates="evaluation", cascade="all, delete-orphan")


class EvaluationRequirement(Base):
    __tablename__ = "evaluation_requirements"

    id = Column(Integer, primary_key=True, index=True)
    evaluation_id = Column(Integer, ForeignKey("evaluations.id"), nullable=False, index=True)
    job_requirement_id = Column(Integer, ForeignKey("job_requirements.id"), nullable=True, index=True)
    requirement_text = Column(Text, nullable=False)
    importance = Column(String(20), nullable=True)
    fit = Column(String(20), nullable=True)
    cv_evidence = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)

    evaluation = relationship("Evaluation", back_populates="requirement_results")
    job_requirement = relationship("JobRequirement", back_populates="evaluation_requirements")


class ApplicationDocument(Base):
    """Relational entity linking an Application with specific versioned Documents used."""
    __tablename__ = "application_documents"

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    document_role = Column(String(100), default="Primary CV") # Primary CV, Tailored Cover Letter, Transcript, Enrollment Cert
    notes = Column(Text, nullable=True)

    application = relationship("Application", back_populates="application_documents")
    document = relationship("Document", back_populates="application_links")


class Feedback(Base):
    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    stage = Column(String(50), default="Application") # Application, Recruiter Review, Functional department review, interview, final
    feedback_date = Column(Date, default=date.today)
    feedback_type = Column(String(50), default="unknown") # Skill gap, Experience, Language, Timing, no capacity, degree mismatch, internship duration, unknown
    raw_feedback = Column(Text, nullable=True) # Full text received from HR
    skill_gap = Column(Text, nullable=True) # Extracted actionable skills missing
    actionable = Column(String(20), default="unclear") # yes, no, unclear
    action_taken = Column(Text, nullable=True) # E.g. Learned Docker, enrolled in German B2 course
    notes = Column(Text, nullable=True)

    application = relationship("Application", back_populates="feedbacks")
    company = relationship("Company", back_populates="feedbacks")


class Interview(Base):
    __tablename__ = "interviews"

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    interview_date = Column(DateTime, nullable=False)
    round_no = Column(Integer, default=1)
    format = Column(String(50), default="Video") # Phone, Video, On-Site, Assessment, other
    participants = Column(String(255), nullable=True)
    topics = Column(Text, nullable=True)
    outcome = Column(String(30), default="scheduled") # scheduled, Completed, passed, rejected, offer, cancelled
    follow_up = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)

    application = relationship("Application", back_populates="interviews")
    company = relationship("Company", back_populates="interviews")


class SearchAlert(Base):
    __tablename__ = "search_alerts"

    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    company_name = Column(String(150), nullable=True)
    platform = Column(String(100), default="LinkedIn") # LinkedIn, StepStone, Indeed, Xing, Company Career Page
    filter_name = Column(String(150), nullable=False)
    country = Column(String(100), default="Germany")
    join_as = Column(String(100), default="Internship") # Internship, Working Student, Junior Full-Time
    keywords = Column(String(255), nullable=True)
    created_date = Column(Date, default=date.today)
    status = Column(String(30), default="Active") # Active, Paused, Expired
    last_checked = Column(Date, nullable=True)
    last_results = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)

    company = relationship("Company", back_populates="search_alerts")
    candidate = relationship("Candidate", back_populates="search_alerts")
