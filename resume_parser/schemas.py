from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ConfidenceSignals(BaseModel):
    source_quality: float = Field(ge=0.0, le=1.0)
    section_match: float = Field(ge=0.0, le=1.0)
    pattern_validity: float = Field(ge=0.0, le=1.0)
    cross_field_consistency: float = Field(ge=0.0, le=1.0)
    model_certainty: float = Field(ge=0.0, le=1.0)


class Confidence(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    signals: ConfidenceSignals
    evidence: list[str] = Field(default_factory=list)


class Skill(BaseModel):
    raw: str
    canonical: str
    category: str = "general"
    confidence: Confidence


class Tool(BaseModel):
    raw: str
    canonical: str
    confidence: Confidence


class ExperienceItem(BaseModel):
    company: str
    title: str
    start_date: str
    end_date: str | None = None
    is_current: bool = False
    summary: str = ""
    skills_used: list[str] = Field(default_factory=list)
    confidence: Confidence


class ProjectItem(BaseModel):
    name: str
    role: str | None = None
    description: str
    impact: str | None = None
    tech_stack: list[str] = Field(default_factory=list)
    confidence: Confidence


class EducationItem(BaseModel):
    institution: str
    degree: str
    field: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    gpa: str | None = None
    confidence: Confidence


class ReviewField(BaseModel):
    path: str
    reason: str
    current_confidence: float = Field(ge=0.0, le=1.0)


class SourceMetadata(BaseModel):
    file_type: Literal["pdf", "docx"]
    pages: int = Field(ge=1)
    extractor: str
    ocr_used: bool = False


class Profile(BaseModel):
    candidate_name: str | None = None
    headline: str | None = None
    skills: list[Skill] = Field(default_factory=list)
    tools: list[Tool] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)


class Quality(BaseModel):
    overall_confidence: float = Field(ge=0.0, le=1.0)
    fields_needing_review: list[ReviewField] = Field(default_factory=list)
    duplicate_groups_resolved: int = Field(default=0, ge=0)


class ParsedResume(BaseModel):
    resume_id: UUID
    version: int = Field(default=1, ge=1)
    status: Literal["parsed", "needs_review", "confirmed", "failed"]
    source: SourceMetadata
    profile: Profile
    quality: Quality


class UploadResponse(BaseModel):
    resume_id: UUID
    status: Literal["uploaded"]
    storage_uri: str
    next_action: Literal["start_parse"]


class ParseRequest(BaseModel):
    force_reparse: bool = False
    pipeline_version: str = "2026.03"
    idempotency_key: str


class ParseResponse(BaseModel):
    parse_job_id: UUID
    status: Literal["queued", "running", "completed", "failed"]
    estimated_seconds: int = 25


class ParseJobStatus(BaseModel):
    parse_job_id: UUID
    status: Literal["queued", "running", "completed", "failed"]
    progress: int = Field(ge=0, le=100)
    stage: str
    error: str | None = None


class Correction(BaseModel):
    path: str
    old_value: Any = None
    new_value: Any
    reason: str


class ConfirmRequest(BaseModel):
    version: int
    corrections: list[Correction] = Field(default_factory=list)
    confirm_final: bool = True


class ConfirmResponse(BaseModel):
    resume_id: UUID
    status: Literal["confirmed", "needs_review"]
    applied_corrections: int
    final_version: int


QuestionCategory = Literal[
    "fundamentals",
    "project_deep_dive",
    "role_specific_stack",
    "debugging_scenario",
]

ExperienceLevel = Literal["junior", "mid", "senior", "staff"]


class AdaptiveFollowUp(BaseModel):
    trigger: str
    follow_up_prompt: str
    intent: str


class QuestionObject(BaseModel):
    question_id: str
    category: QuestionCategory
    prompt: str
    focus_topic: str
    difficulty: int = Field(ge=1, le=5)
    expected_time_minutes: int = Field(ge=3, le=30)
    ideal_answer_checklist: list[str] = Field(default_factory=list, min_length=3, max_length=8)
    adaptive_follow_ups: list[AdaptiveFollowUp] = Field(default_factory=list)
    quality_score: float = Field(ge=0.0, le=1.0)


class QuestionGenerationRequest(BaseModel):
    candidate_profile: dict[str, Any] | None = None
    parsed_profile: dict[str, Any] | None = None
    target_role: str = "Backend Engineer"
    experience_level: ExperienceLevel = "mid"
    focus_topics: list[str] = Field(default_factory=list)
    previous_session_weaknesses: list[str] = Field(default_factory=list)
    question_count: int = Field(default=10, ge=4, le=20)

    @model_validator(mode="before")
    @classmethod
    def normalize_profile_keys(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if value.get("candidate_profile") is None and value.get("parsed_profile") is not None:
            value["candidate_profile"] = value.get("parsed_profile")
        return value


class QuestionValidationRule(BaseModel):
    rule_id: str
    description: str


class RegenerationStrategy(BaseModel):
    when_to_regenerate: str
    actions: list[str] = Field(default_factory=list)


class QuestionFrameworkMetadata(BaseModel):
    prompt_templates: dict[str, str]
    json_schema: dict[str, Any]
    validation_rules: list[QuestionValidationRule]
    regeneration_strategy: RegenerationStrategy


class QuestionGenerationResponse(BaseModel):
    target_role: str
    experience_level: ExperienceLevel
    generated_count: int
    questions: list[QuestionObject]
    overall_quality_score: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)


AnswerEvaluationVerdict = Literal["weak", "average", "strong"]


class AnswerEvaluationRequest(BaseModel):
    resume_id: UUID | None = None
    session_id: str | None = None
    question_id: str | None = None
    question: str
    candidate_answer: str = Field(min_length=8)
    ideal_answer_checklist: list[str] = Field(default_factory=list, max_length=12)
    target_role: str = "Backend Engineer"
    experience_level: ExperienceLevel = "mid"
    focus_topic: str | None = None
    difficulty: int = Field(default=3, ge=1, le=5)
    skipped: bool = False

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        if not value.get("candidate_answer") and value.get("answer"):
            value["candidate_answer"] = value["answer"]

        if not value.get("focus_topic") and value.get("topic"):
            value["focus_topic"] = value["topic"]

        if not value.get("question") and value.get("question_text"):
            value["question"] = value["question_text"]

        if value.get("skipped") and not value.get("candidate_answer"):
            value["candidate_answer"] = "Skipped by candidate."

        return value


class RubricCriterionDefinition(BaseModel):
    criterion: str
    score_min: int = Field(default=0, ge=0, le=10)
    score_max: int = Field(default=5, ge=1, le=10)
    weight: float = Field(ge=0.0, le=1.0)
    scoring_guide: list[str] = Field(default_factory=list)


class CriterionScore(BaseModel):
    value: int = Field(ge=0, le=5)
    rationale: str


class EvidenceSnippet(BaseModel):
    criterion: str
    quote: str
    reason: str


class WorkedEvaluationExample(BaseModel):
    label: AnswerEvaluationVerdict
    question: str
    answer_excerpt: str
    summary: str


class AnswerEvaluationResponse(BaseModel):
    evaluation_id: str | None = None
    question: str
    target_role: str
    experience_level: ExperienceLevel
    focus_topic: str | None = None
    difficulty: int = Field(ge=1, le=5)
    correctness: CriterionScore
    depth: CriterionScore
    reasoning_tradeoffs: CriterionScore
    clarity_communication: CriterionScore
    confidence_signal: CriterionScore
    weighted_final_score_100: float = Field(ge=0.0, le=100.0)
    weighted_final_score_10: float = Field(ge=0.0, le=10.0)
    verdict: AnswerEvaluationVerdict
    confidence_in_score: float = Field(ge=0.0, le=1.0)
    evidence_snippets: list[EvidenceSnippet] = Field(default_factory=list)
    missed_key_points: list[str] = Field(default_factory=list)
    adaptive_follow_up_prompts: list[str] = Field(default_factory=list)
    better_answer_coaching: str
    formula_version: str = "v1"
    warnings: list[str] = Field(default_factory=list)

    # Compatibility fields used by the current vanilla interview page.
    score: float = Field(ge=0.0, le=1.0)
    feedback: str
    weak: bool


class AnswerEvaluationFrameworkMetadata(BaseModel):
    rubric_table: list[RubricCriterionDefinition]
    evaluation_prompt_templates: dict[str, str]
    json_schema: dict[str, Any]
    post_processing_formula: str
    calibration_strategy: list[str]
    worked_examples: list[WorkedEvaluationExample]


OrchestrationActionType = Literal["ask_new_question", "ask_follow_up", "offer_hint", "end_session"]
OrchestrationStopReason = Literal[
    "question_budget_reached",
    "time_budget_exhausted",
    "repeated_idk",
    "minimum_coverage_met",
    "manual_end",
]


class OrchestrationTurn(BaseModel):
    question_id: str
    category: QuestionCategory
    focus_topic: str
    difficulty: int = Field(ge=1, le=5)
    expected_time_minutes: int = Field(ge=1, le=45)
    answer_text: str = ""
    answer_score: float = Field(default=0.0, ge=0.0, le=1.0)
    answered_seconds: int = Field(default=0, ge=0)
    skipped: bool = False
    off_topic: bool = False
    used_hint: bool = False


class OrchestrationStateRequest(BaseModel):
    target_role: str
    experience_level: ExperienceLevel = "mid"
    total_time_minutes: int = Field(default=35, ge=10, le=120)
    remaining_time_minutes: int = Field(default=35, ge=0, le=120)
    focus_topics: list[str] = Field(default_factory=list)
    previous_session_weaknesses: list[str] = Field(default_factory=list)
    question_pool: list[QuestionObject] = Field(default_factory=list)
    asked_turns: list[OrchestrationTurn] = Field(default_factory=list)
    max_questions: int = Field(default=10, ge=3, le=30)
    idk_streak: int = Field(default=0, ge=0, le=10)


class OrchestrationPolicyScore(BaseModel):
    question_id: str
    category: QuestionCategory
    topic: str
    composite_score: float = Field(ge=0.0, le=1.0)
    quality_component: float = Field(ge=0.0, le=1.0)
    coverage_component: float = Field(ge=0.0, le=1.0)
    difficulty_component: float = Field(ge=0.0, le=1.0)
    time_component: float = Field(ge=0.0, le=1.0)
    weakness_component: float = Field(ge=0.0, le=1.0)


class OrchestrationDecision(BaseModel):
    action: OrchestrationActionType
    reason: str
    selected_question: QuestionObject | None = None
    follow_up_prompt: str | None = None
    hint_prompt: str | None = None
    stop_reason: OrchestrationStopReason | None = None
    policy_scores: list[OrchestrationPolicyScore] = Field(default_factory=list)


class OrchestrationSummary(BaseModel):
    total_questions_attempted: int
    answered_questions: int
    skipped_questions: int
    coverage_by_category: dict[str, int]
    average_score: float = Field(ge=0.0, le=1.0)
    weak_topics: list[str] = Field(default_factory=list)
    strong_topics: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    time_overrun: bool = False


class OrchestrationFrameworkMetadata(BaseModel):
    decision_policy: str
    pseudocode: str
    stop_conditions: list[str]
    follow_up_policy: list[str]
    hint_policy: list[str]
    summarization_logic: list[str]
    edge_case_rules: list[str]


ReadinessBandLabel = Literal["beginner", "intermediate", "ready"]


class DashboardScoringBand(BaseModel):
    label: ReadinessBandLabel
    min_score: float = Field(ge=0.0, le=100.0)
    max_score: float = Field(ge=0.0, le=100.0)
    meaning: str


class DashboardSessionSummaryItem(BaseModel):
    session_id: str
    completed_at: str
    question_count: int = Field(ge=0)
    avg_score_100: float = Field(ge=0.0, le=100.0)
    readiness_score_100: float = Field(ge=0.0, le=100.0)
    readiness_band: ReadinessBandLabel
    weak_area_count: int = Field(ge=0)


class DashboardRadarData(BaseModel):
    labels: list[str] = Field(default_factory=list)
    values: list[float] = Field(default_factory=list)


class DashboardQuestionBreakdownItem(BaseModel):
    evaluation_id: str
    session_id: str
    question_id: str | None = None
    question: str
    topic: str
    score_100: float = Field(ge=0.0, le=100.0)
    verdict: str
    is_weak: bool = False
    missed_key_points: list[str] = Field(default_factory=list)
    coaching: str
    created_at: str


class DashboardWeakAreaItem(BaseModel):
    topic: str
    severity: Literal["critical", "high", "moderate"]
    avg_score_100: float = Field(ge=0.0, le=100.0)
    frequency: int = Field(ge=1)
    evidence_points: list[str] = Field(default_factory=list)


class DashboardTrendPoint(BaseModel):
    session_id: str
    completed_at: str
    readiness_score_100: float = Field(ge=0.0, le=100.0)
    avg_score_100: float = Field(ge=0.0, le=100.0)


class DashboardStudyPlanItem(BaseModel):
    priority: Literal["P1", "P2", "P3"]
    title: str
    action: str
    rationale: str
    estimated_days: int = Field(ge=1, le=30)


class DashboardResponse(BaseModel):
    resume_id: UUID
    candidate_name: str
    target_role: str
    readiness_score_100: float = Field(ge=0.0, le=100.0)
    readiness_band: ReadinessBandLabel
    scoring_bands: list[DashboardScoringBand]
    session_summary: list[DashboardSessionSummaryItem]
    skill_radar: DashboardRadarData
    question_breakdown: list[DashboardQuestionBreakdownItem]
    weak_areas: list[DashboardWeakAreaItem]
    trend: list[DashboardTrendPoint]
    recommended_study_plan: list[DashboardStudyPlanItem]
    feedback_templates: list[str] = Field(default_factory=list)
