from datetime import date, datetime
from typing import Optional, List, Any, Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator

# ----------------- CANDIDATE -----------------
class CandidateBase(BaseModel):
    profile_name: str
    degree: Optional[str] = None
    uni: Optional[str] = None
    target: Optional[str] = None
    availability: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None

class CandidateCreate(CandidateBase):
    pass

class CandidateRead(CandidateBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


# ----------------- SKILL -----------------
class SkillBase(BaseModel):
    name: str
    category: Optional[str] = "Technical"
    evidence_source: Optional[str] = None
    current_level: Optional[str] = "Intermediate"
    notes: Optional[str] = None
    candidate_id: Optional[int] = None

class SkillCreate(SkillBase):
    pass

class SkillRead(SkillBase):
    id: int
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

# ----------------- COMPANY -----------------
class CompanyBase(BaseModel):
    name: str
    city: Optional[str] = None
    region: Optional[str] = None
    webpage: Optional[str] = None
    technical_field: Optional[str] = None
    class_grade: Optional[str] = "B" # A, B, B-/C, C, D
    company_eligibility: Optional[str] = "yes" # yes, no, unclear
    evidence_confidence: Optional[str] = "High" # High, Medium, Low, 85%
    recommended_effort: Optional[str] = "Medium" # Deep, Medium+, Medium, Light, Standard
    research_status: Optional[str] = "Evaluating" # Pending, Evaluating, Eligible, Not Eligible, Unclear, Applied, Alert Active, Not Suitable
    notes: Optional[str] = None

class CompanyCreate(CompanyBase):
    pass

class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    webpage: Optional[str] = None
    technical_field: Optional[str] = None
    class_grade: Optional[str] = None
    company_eligibility: Optional[str] = None
    evidence_confidence: Optional[str] = None
    recommended_effort: Optional[str] = None
    research_status: Optional[str] = None
    notes: Optional[str] = None

class CompanyRead(CompanyBase):
    id: int
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


# ----------------- CANDIDATE / COMPANY ASSESSMENT -----------------
class CandidateCompanyBase(BaseModel):
    candidate_id: int
    company_id: int
    class_grade: Optional[str] = "B"
    company_eligibility: Optional[str] = "yes"
    evidence_confidence: Optional[str] = "High"
    recommended_effort: Optional[str] = "Medium"
    research_status: Optional[str] = None
    notes: Optional[str] = None

class CandidateCompanyCreate(CandidateCompanyBase):
    pass

class CandidateCompanyRead(CandidateCompanyBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


# ----------------- JOB / POSITION -----------------
class JobBase(BaseModel):
    company_id: int
    title: str
    source_url: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    source_platform: Optional[str] = None
    raw_source_text: Optional[str] = None
    structured_extraction: Optional[str] = None
    confirmation_status: Optional[str] = "draft"
    normalized_source_url: Optional[str] = None
    source_hash: Optional[str] = None
    version_number: int = 1
    supersedes_job_id: Optional[int] = None
    version_source: Optional[str] = "imported"
    confirmed_at: Optional[datetime] = None
    last_edited_at: Optional[datetime] = None

class JobCreate(JobBase):
    pass

class JobRead(JobBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class JobRequirementBase(BaseModel):
    job_id: int
    requirement: str
    category: Optional[str] = None
    importance: Optional[str] = None
    source_text: Optional[str] = None

class JobRequirementCreate(JobRequirementBase):
    pass

class JobRequirementRead(JobRequirementBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


# ----------------- UNCONFIRMED JOB INGESTION PREVIEW -----------------
RequirementCategory = Literal["Technical", "Experience", "Education", "Language", "Eligibility", "Domain", "Soft Skill", "Other"]

class JobExtractionRequirement(BaseModel):
    text: str = Field(min_length=1, max_length=1000, strict=True)
    category: RequirementCategory = "Other"
    importance: Literal["required", "preferred"]
    source_evidence: Optional[str] = Field(default=None, max_length=2000, strict=True)
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value):
        supported = {"Technical", "Experience", "Education", "Language", "Eligibility", "Domain", "Soft Skill", "Other"}
        return value if value in supported else "Other"

class JobExtractionPreview(BaseModel):
    company_name: Optional[str] = Field(default=None, max_length=300, strict=True)
    position_title: Optional[str] = Field(default=None, max_length=300, strict=True)
    location: Optional[str] = Field(default=None, max_length=200, strict=True)
    job_description: Optional[str] = Field(default=None, max_length=12000, strict=True)
    required_qualifications: List[JobExtractionRequirement] = Field(default_factory=list)
    preferred_qualifications: List[JobExtractionRequirement] = Field(default_factory=list)
    source_url: Optional[str] = Field(default=None, max_length=500, strict=True)
    source_platform: Optional[str] = Field(default=None, max_length=100, strict=True)
    evidence_confidence: Optional[Literal["low", "medium", "high"]] = None
    model_config = ConfigDict(extra="forbid", strict=True)

class JobExtractionServiceResult(BaseModel):
    preview: JobExtractionPreview
    latency_ms: int
    usage: dict[str, Optional[int]]
    response_format_json: bool
    thinking_disabled: bool

class JobIngestRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)

class JobIngestResponse(BaseModel):
    state: Literal["preview"] = "preview"
    preview: JobExtractionPreview
    source_text: str
    source_text_truncated: bool
    page_title: Optional[str] = None
    canonical_url: Optional[str] = None
    latency_ms: int
    usage: dict[str, Optional[int]]
    response_format_json: bool
    thinking_disabled: bool

class JobConfirmRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=300)
    position_title: str = Field(min_length=1, max_length=300)
    source_url: Optional[str] = Field(default=None, max_length=500)
    location: Optional[str] = Field(default=None, max_length=200)
    job_description: Optional[str] = Field(default=None, max_length=12000)
    source_platform: Optional[str] = Field(default=None, max_length=100)
    source_text: Optional[str] = Field(default=None, max_length=16000)
    required_qualifications: List[JobExtractionRequirement] = Field(default_factory=list)
    preferred_qualifications: List[JobExtractionRequirement] = Field(default_factory=list)
    version_source: Literal["imported", "source_update", "pasted_text"] = "imported"
    supersedes_job_id: Optional[int] = None
    source_hash: Optional[str] = Field(default=None, min_length=64, max_length=64)

class JobConfirmResponse(BaseModel):
    company: CompanyRead
    job: JobRead
    requirements: List[JobRequirementRead]

class JobDuplicateInfo(BaseModel):
    id: int
    company_name: str
    title: str
    version_number: int
    confirmed_at: Optional[datetime] = None
    source_url: Optional[str] = None
    version_source: Optional[str] = None

class JobDuplicateResponse(BaseModel):
    state: Literal["duplicate"] = "duplicate"
    message: str = "This job URL already exists."
    normalized_source_url: str
    latest_job: JobDuplicateInfo

class JobUpdateCheckRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)

class JobUpdateCheckResponse(JobIngestResponse):
    state: Literal["preview", "unchanged"] = "preview"
    message: Optional[str] = None
    existing_job_id: Optional[int] = None

class JobPasteTextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200000)

class JobManualVersionRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=300)
    position_title: str = Field(min_length=1, max_length=300)
    location: Optional[str] = Field(default=None, max_length=200)
    job_description: Optional[str] = Field(default=None, max_length=12000)
    source_platform: Optional[str] = Field(default=None, max_length=100)
    required_qualifications: List[JobExtractionRequirement] = Field(default_factory=list)
    preferred_qualifications: List[JobExtractionRequirement] = Field(default_factory=list)

# ----------------- COMPANY REQUIREMENT -----------------
class CompanyRequirementBase(BaseModel):
    requirement: str
    company_id: Optional[int] = None
    application_id: Optional[int] = None
    category: Optional[str] = "Technical"
    importance: Optional[str] = "Medium" # High, Medium, Low
    user_evidence: Optional[str] = None
    fit: Optional[str] = "partial" # strong, good, partial, gap, unknown
    gap_action: Optional[str] = None
    source_url: Optional[str] = None

class CompanyRequirementCreate(CompanyRequirementBase):
    pass

class CompanyRequirementRead(CompanyRequirementBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

# ----------------- DAILY BATCH -----------------
class DailyBatchBase(BaseModel):
    candidate_id: Optional[int] = None
    batch_date: date = Field(default_factory=date.today)
    day_no: int = 1
    target_evaluation: int = 5
    target_application: int = 3
    actual_evaluation: int = 0
    actual_application: int = 0
    focus: Optional[str] = None
    status: Optional[str] = "in progress" # planned, in progress, completed, blocked, skipped
    notes: Optional[str] = None
    next_pool: Optional[str] = None

class DailyBatchCreate(DailyBatchBase):
    pass

class DailyBatchUpdate(BaseModel):
    day_no: Optional[int] = None
    target_evaluation: Optional[int] = None
    target_application: Optional[int] = None
    actual_evaluation: Optional[int] = None
    actual_application: Optional[int] = None
    focus: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    next_pool: Optional[str] = None

class DailyBatchRead(DailyBatchBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

# ----------------- DOCUMENT & RELATIONAL JOIN -----------------
class DocumentBase(BaseModel):
    candidate_id: Optional[int] = None
    name: str
    doc_type: Optional[str] = "CV" # CV, Cover letter, Studienbescheinigung, Transcript, Certificate, Other
    version_date: Optional[date] = Field(default_factory=date.today)
    status: Optional[str] = "active" # active, archived, deprecated
    owner_note: Optional[str] = None
    file_link: Optional[str] = None
    stored_path: Optional[str] = None
    raw_text: Optional[str] = None
    structured_extraction: Optional[str] = None
    confirmation_status: Optional[str] = "unconfirmed"
    extraction_error: Optional[str] = None
    file_hash: Optional[str] = None
    text_hash: Optional[str] = None
    extracted_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    extraction_confidence: Optional[str] = None
    parser_version: Optional[str] = None
    layout_metadata: Optional[str] = None
    layout_confidence: Optional[str] = None

class DocumentCreate(DocumentBase):
    pass

class DocumentRead(DocumentBase):
    id: int
    stored_path: Optional[str] = Field(default=None, exclude=True)
    raw_text: Optional[str] = Field(default=None, exclude=True)
    structured_extraction: Optional[str] = Field(default=None, exclude=True)
    has_local_file: bool = False
    can_open_file: bool = False
    can_reprocess: bool = False
    can_compare_affinda: bool = False
    is_confirmed: bool = False
    file_open_mode: Optional[Literal["local", "external"]] = None
    model_config = ConfigDict(from_attributes=True)

# ----------------- STRICT CV INGESTION PROFILE -----------------
class CVSkill(BaseModel):
    name: str = Field(min_length=1, max_length=200, strict=True)
    category: Optional[str] = Field(default=None, max_length=100, strict=True)
    level: Optional[str] = Field(default=None, max_length=100, strict=True)
    evidence: Optional[str] = Field(default=None, max_length=2000, strict=True)
    model_config = ConfigDict(extra="forbid", strict=True)

class CVWorkExperience(BaseModel):
    organization: Optional[str] = Field(default=None, max_length=300, strict=True)
    position: Optional[str] = Field(default=None, max_length=300, strict=True)
    location: Optional[str] = Field(default=None, max_length=200, strict=True)
    start_date: Optional[str] = Field(default=None, max_length=100, strict=True)
    end_date: Optional[str] = Field(default=None, max_length=100, strict=True)
    description: Optional[str] = Field(default=None, max_length=4000, strict=True)
    skills_or_tools: List[str] = Field(default_factory=list)
    evidence: Optional[str] = Field(default=None, max_length=2000, strict=True)
    model_config = ConfigDict(extra="forbid", strict=True)

class CVEducation(BaseModel):
    institution: Optional[str] = Field(default=None, max_length=300, strict=True)
    degree: Optional[str] = Field(default=None, max_length=300, strict=True)
    field: Optional[str] = Field(default=None, max_length=300, strict=True)
    start_date: Optional[str] = Field(default=None, max_length=100, strict=True)
    end_date: Optional[str] = Field(default=None, max_length=100, strict=True)
    status: Optional[str] = Field(default=None, max_length=100, strict=True)
    evidence: Optional[str] = Field(default=None, max_length=2000, strict=True)
    model_config = ConfigDict(extra="forbid", strict=True)

class CVLanguage(BaseModel):
    language: str = Field(min_length=1, max_length=100, strict=True)
    level: Optional[str] = Field(default=None, max_length=100, strict=True)
    evidence: Optional[str] = Field(default=None, max_length=2000, strict=True)
    model_config = ConfigDict(extra="forbid", strict=True)

class CVCertification(BaseModel):
    name: str = Field(min_length=1, max_length=300, strict=True)
    issuer: Optional[str] = Field(default=None, max_length=300, strict=True)
    date: Optional[str] = Field(default=None, max_length=100, strict=True)
    evidence: Optional[str] = Field(default=None, max_length=2000, strict=True)
    model_config = ConfigDict(extra="forbid", strict=True)

class CVProject(BaseModel):
    name: str = Field(min_length=1, max_length=300, strict=True)
    description: Optional[str] = Field(default=None, max_length=4000, strict=True)
    technologies: List[str] = Field(default_factory=list)
    evidence: Optional[str] = Field(default=None, max_length=2000, strict=True)
    model_config = ConfigDict(extra="forbid", strict=True)

class CVProfile(BaseModel):
    professional_summary: Optional[str] = Field(default=None, max_length=6000, strict=True)
    skills: List[CVSkill] = Field(default_factory=list)
    work_experience: List[CVWorkExperience] = Field(default_factory=list)
    education: List[CVEducation] = Field(default_factory=list)
    languages: List[CVLanguage] = Field(default_factory=list)
    certifications: List[CVCertification] = Field(default_factory=list)
    projects: List[CVProject] = Field(default_factory=list)
    other_qualifications: List[str] = Field(default_factory=list)
    extraction_confidence: Literal["high", "medium", "low"]
    extraction_warnings: List[str] = Field(default_factory=list)
    model_config = ConfigDict(extra="forbid", strict=True)

class CVExtractionServiceResult(BaseModel):
    profile: CVProfile
    latency_ms: int
    usage: dict[str, Optional[int]]
    response_format_json: bool
    thinking_disabled: bool

class CVConfirmRequest(BaseModel):
    candidate_id: int
    profile: CVProfile

class CVReprocessRequest(BaseModel):
    candidate_id: int

class CVProviderPreviewRequest(BaseModel):
    candidate_id: int
    provider: Literal["affinda"] = "affinda"

class ApplicationDocumentCreate(BaseModel):
    document_id: int
    document_role: Optional[str] = "Primary CV" # Primary CV, Tailored Cover Letter, etc.
    notes: Optional[str] = None

class ApplicationDocumentRead(BaseModel):
    id: int
    application_id: int
    document_id: int
    document_role: str
    notes: Optional[str] = None
    document: Optional[DocumentRead] = None
    model_config = ConfigDict(from_attributes=True)

# ----------------- APPLICATION -----------------
class ApplicationBase(BaseModel):
    candidate_id: Optional[int] = None
    company_id: int
    job_id: Optional[str] = None
    job_posting_id: Optional[int] = None
    job_title: str
    job_url: Optional[str] = None
    application_date: Optional[date] = Field(default_factory=date.today)
    daily_batch_id: Optional[int] = None
    application_channel: Optional[str] = "Direct"
    application_type: Optional[str] = "Direct" # Direct, Initiative, Referral, Portal, Agency
    internship_content_eligibility: Optional[str] = "yes"
    company_class: Optional[str] = "B"
    company_recommended_effort: Optional[str] = "Medium"
    status: Optional[str] = "Preparing" # not started, Preparing, Ready, Applied, Response, Interview, Rejected, offer, Withdrawn
    current_stage: Optional[str] = "Portal submitted" # Portal submitted, Recruiter review, functional department review, Interview, Offer, closed, Submitted
    feedback_status: Optional[str] = "not yet" # not yet, requested, received, no response, not applicable
    follow_up_date: Optional[date] = None
    response_date: Optional[date] = None
    result: Optional[str] = None
    next_action: Optional[str] = None
    notes: Optional[str] = None

class ApplicationCreate(ApplicationBase):
    attached_documents: Optional[List[ApplicationDocumentCreate]] = None

class ApplicationUpdate(BaseModel):
    job_id: Optional[str] = None
    job_title: Optional[str] = None
    job_url: Optional[str] = None
    application_date: Optional[date] = None
    daily_batch_id: Optional[int] = None
    application_channel: Optional[str] = None
    application_type: Optional[str] = None
    internship_content_eligibility: Optional[str] = None
    company_class: Optional[str] = None
    company_recommended_effort: Optional[str] = None
    status: Optional[str] = None
    current_stage: Optional[str] = None
    feedback_status: Optional[str] = None
    follow_up_date: Optional[date] = None
    response_date: Optional[date] = None
    result: Optional[str] = None
    next_action: Optional[str] = None
    notes: Optional[str] = None

class ApplicationRead(ApplicationBase):
    id: int
    company: Optional[CompanyRead] = None
    application_documents: List[ApplicationDocumentRead] = []
    model_config = ConfigDict(from_attributes=True)

# ----------------- FEEDBACK -----------------
class FeedbackBase(BaseModel):
    application_id: int
    company_id: Optional[int] = None
    stage: Optional[str] = "Application" # Application, Recruiter Review, Functional department review, interview, final
    feedback_date: Optional[date] = Field(default_factory=date.today)
    feedback_type: Optional[str] = "unknown" # Skill gap, Experience, Language, Timing, no capacity, degree mismatch, internship duration, unknown
    raw_feedback: Optional[str] = None
    skill_gap: Optional[str] = None
    actionable: Optional[str] = "unclear" # yes, no, unclear
    action_taken: Optional[str] = None
    notes: Optional[str] = None

class FeedbackCreate(FeedbackBase):
    add_to_learning_curve: Optional[bool] = True

class FeedbackRead(FeedbackBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

# ----------------- INTERVIEW -----------------
class InterviewBase(BaseModel):
    application_id: int
    company_id: Optional[int] = None
    interview_date: datetime
    round_no: Optional[int] = 1
    format: Optional[str] = "Video" # Phone, Video, On-Site, Assessment, other
    participants: Optional[str] = None
    topics: Optional[str] = None
    outcome: Optional[str] = "scheduled" # scheduled, Completed, passed, rejected, offer, cancelled
    follow_up: Optional[str] = None
    notes: Optional[str] = None

class InterviewCreate(InterviewBase):
    pass

class InterviewRead(InterviewBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

# ----------------- SEARCH ALERT -----------------
class SearchAlertBase(BaseModel):
    candidate_id: Optional[int] = None
    company_id: Optional[int] = None
    company_name: Optional[str] = None
    platform: Optional[str] = "LinkedIn"
    filter_name: str
    country: Optional[str] = "Germany"
    join_as: Optional[str] = "Internship"
    keywords: Optional[str] = None
    created_date: Optional[date] = Field(default_factory=date.today)
    status: Optional[str] = "Active"
    last_checked: Optional[date] = None
    last_results: Optional[str] = None
    notes: Optional[str] = None

class SearchAlertCreate(SearchAlertBase):
    pass

class SearchAlertRead(SearchAlertBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


# ----------------- PERSISTED CV / JOB EVALUATION -----------------
class EvaluationBase(BaseModel):
    candidate_id: int
    document_id: int
    job_id: int
    overall_score: Optional[float] = None
    requirement_coverage: Optional[float] = None
    confidence: Optional[str] = None
    summary: Optional[str] = None
    structured_result: Optional[str] = None
    raw_model_result: Optional[str] = None
    model_identifier: Optional[str] = None

class EvaluationCreate(EvaluationBase):
    pass

class EvaluationRead(EvaluationBase):
    id: int
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class EvaluationRequirementBase(BaseModel):
    evaluation_id: int
    job_requirement_id: Optional[int] = None
    requirement_text: str
    importance: Optional[str] = None
    fit: Optional[str] = None
    cv_evidence: Optional[str] = None
    reason: Optional[str] = None

class EvaluationRequirementCreate(EvaluationRequirementBase):
    pass

class EvaluationRequirementRead(EvaluationRequirementBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

# ----------------- AI REQUEST & RESPONSE SCHEMAS -----------------
class AIEvaluateFitRequest(BaseModel):
    company_name: str = Field(max_length=200)
    job_title: str = Field(max_length=300)
    job_description: Optional[str] = Field(default=None, max_length=12000)
    technical_field: Optional[str] = Field(default=None, max_length=200)
    requirements_text: Optional[str] = Field(default=None, max_length=12000)
    candidate_id: Optional[int] = None

class AIEvaluateFitResponse(BaseModel):
    class_grade: str # A, B, B-/C, C, D
    fit_score: int # 0-100
    recommended_effort: str # Deep, Medium+, Medium, Light, Standard
    evidence_confidence: str # High, Medium, Low
    matched_skills: List[str]
    missing_skills: List[str]
    rationale: str
    tailoring_suggestions: List[str]

class AIExtractFeedbackRequest(BaseModel):
    application_id: int
    raw_feedback_text: str = Field(max_length=12000)
    stage: Optional[str] = Field(default="Application", max_length=100)

class AIExtractFeedbackResponse(BaseModel):
    feedback_type: str # Skill gap, Experience, Language, Timing, no capacity, degree mismatch, internship duration, unknown
    is_actionable: str # yes, no, unclear
    extracted_skill_gaps: List[str]
    rejection_summary: str
    polite_feedback_response_draft: str
    action_plan_for_candidate: str

class AIGenerateFeedbackDraftRequest(BaseModel):
    application_id: int
    contact_person: Optional[str] = Field(default=None, max_length=200)
    tone: Optional[str] = Field(default="Courteous & Growth-Oriented", max_length=100)
    language: Optional[str] = Field(default="English", max_length=20) # English or German

class AIGenerateFeedbackDraftResponse(BaseModel):
    subject: str
    body: str
    hr_signal_explanation: str

class LearningCurveStats(BaseModel):
    total_skills_tracked: int
    skills_with_evidence: int
    skill_gaps_identified: int
    skills_addressed: int
    skill_categories: dict
    feedback_distribution: dict
    conversion_by_class: dict
    daily_application_velocity: List[dict]
    forecast_text: str
