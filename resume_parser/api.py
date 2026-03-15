from __future__ import annotations

from collections import defaultdict
import re
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile

from .config import settings
from .evaluation_engine import evaluation_engine
from .orchestration_engine import orchestration_engine
from .pipeline import pipeline
from .question_engine import question_engine
from .repository import repository
from .schemas import (
    AnswerEvaluationFrameworkMetadata,
    AnswerEvaluationRequest,
    AnswerEvaluationResponse,
    ConfirmRequest,
    ConfirmResponse,
    DashboardQuestionBreakdownItem,
    DashboardRadarData,
    DashboardResponse,
    DashboardScoringBand,
    DashboardSessionSummaryItem,
    DashboardStudyPlanItem,
    DashboardTrendPoint,
    DashboardWeakAreaItem,
    OrchestrationDecision,
    OrchestrationFrameworkMetadata,
    OrchestrationStateRequest,
    OrchestrationSummary,
    ParseJobStatus,
    ParseRequest,
    ParseResponse,
    ParsedResume,
    QuestionFrameworkMetadata,
    QuestionGenerationRequest,
    QuestionGenerationResponse,
    UploadResponse,
)

router = APIRouter(prefix="/v1", tags=["resume-parser"])

_ALLOWED_EXTENSIONS = {".pdf": "pdf", ".docx": "docx"}


@router.post("/resumes/upload", response_model=UploadResponse, status_code=201)
async def upload_resume(
    file: UploadFile = File(...),
    candidate_id: str = Form(...),
    consent_version: str = Form(...),
) -> UploadResponse:
    extension = Path(file.filename or "").suffix.lower()
    file_type = _ALLOWED_EXTENSIONS.get(extension)
    if not file_type:
        raise HTTPException(status_code=400, detail="Only PDF and DOCX files are supported")

    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(raw_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File exceeds 10MB limit")

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    resume_id = repository.create_resume(
        candidate_id=candidate_id,
        consent_version=consent_version,
        file_path="",
        file_type=file_type,
    )
    storage_path = settings.upload_dir / f"{resume_id}{extension}"
    storage_path.write_bytes(raw_bytes)

    # Store finalized path and keep status as uploaded.
    resume = repository.get_resume(resume_id)
    if not resume:
        raise HTTPException(status_code=500, detail="Failed to initialize resume record")

    repository.update_resume_file_path(resume_id, str(storage_path))

    return UploadResponse(
        resume_id=resume_id,
        status="uploaded",
        storage_uri=str(storage_path),
        next_action="start_parse",
    )


@router.post("/resumes/{resume_id}/parse", response_model=ParseResponse, status_code=202)
def start_parse(
    resume_id: UUID,
    payload: ParseRequest,
    background_tasks: BackgroundTasks,
) -> ParseResponse:
    resume = repository.get_resume(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    if resume["status"] in {"parsed", "needs_review", "confirmed"} and not payload.force_reparse:
        raise HTTPException(status_code=409, detail="Resume already parsed. Set force_reparse=true to parse again")

    parse_job_id = repository.create_parse_job(resume_id)
    repository.update_resume_status(resume_id, "parsing")
    background_tasks.add_task(_run_parse_job, parse_job_id, resume_id)

    return ParseResponse(parse_job_id=parse_job_id, status="queued", estimated_seconds=25)


@router.get("/parse-jobs/{parse_job_id}", response_model=ParseJobStatus)
def get_parse_job(parse_job_id: UUID) -> ParseJobStatus:
    parse_job = repository.get_parse_job(parse_job_id)
    if not parse_job:
        raise HTTPException(status_code=404, detail="Parse job not found")

    return ParseJobStatus(
        parse_job_id=UUID(parse_job["id"]),
        status=parse_job["status"],
        progress=parse_job["progress"],
        stage=parse_job["stage"],
        error=parse_job["error"],
    )


@router.get("/resumes/{resume_id}/parsed", response_model=ParsedResume)
def get_parsed_resume(resume_id: UUID) -> ParsedResume:
    parsed = repository.get_parsed_resume(resume_id)
    if not parsed:
        raise HTTPException(status_code=404, detail="Parsed resume not found")
    return ParsedResume.model_validate(parsed)


@router.patch("/resumes/{resume_id}/confirm", response_model=ConfirmResponse)
def confirm_resume(resume_id: UUID, payload: ConfirmRequest) -> ConfirmResponse:
    parsed = repository.get_parsed_resume(resume_id)
    if not parsed:
        raise HTTPException(status_code=404, detail="Parsed resume not found")

    updated_payload: dict[str, Any] = parsed

    for correction in payload.corrections:
        _apply_json_path_update(updated_payload, correction.path, correction.new_value)

    review_fields = updated_payload.get("quality", {}).get("fields_needing_review", [])
    corrected_paths = {correction.path for correction in payload.corrections}
    review_fields = [field for field in review_fields if field.get("path") not in corrected_paths]
    updated_payload.setdefault("quality", {})["fields_needing_review"] = review_fields

    status = "confirmed" if payload.confirm_final and not review_fields else "needs_review"
    updated_payload["status"] = status

    try:
        final_version = repository.apply_corrections(
            resume_id,
            current_version=payload.version,
            corrections=[correction.model_dump() for correction in payload.corrections],
            parsed_payload=updated_payload,
            status=status,
        )
    except RuntimeError as exc:
        if str(exc) == "version_conflict":
            raise HTTPException(status_code=409, detail="Version conflict") from exc
        raise
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return ConfirmResponse(
        resume_id=resume_id,
        status=status,
        applied_corrections=len(payload.corrections),
        final_version=final_version,
    )


@router.post("/interviews/questions", response_model=QuestionGenerationResponse)
def generate_interview_questions(payload: QuestionGenerationRequest) -> QuestionGenerationResponse:
    return question_engine.generate(payload)


@router.get("/interviews/questions/framework", response_model=QuestionFrameworkMetadata)
def get_question_framework() -> QuestionFrameworkMetadata:
    metadata = question_engine.framework_metadata()
    return QuestionFrameworkMetadata.model_validate(metadata)


@router.post("/interviews/evaluate", response_model=AnswerEvaluationResponse)
def evaluate_interview_answer(payload: AnswerEvaluationRequest) -> AnswerEvaluationResponse:
    evaluation = evaluation_engine.evaluate(payload)

    evaluation_id = repository.save_answer_evaluation(
        resume_id=payload.resume_id,
        session_id=payload.session_id,
        question_id=payload.question_id,
        request_payload=payload.model_dump(mode="json"),
        response_payload=evaluation.model_dump(mode="json"),
    )
    evaluation.evaluation_id = str(evaluation_id)
    return evaluation


@router.get("/interviews/evaluate/framework", response_model=AnswerEvaluationFrameworkMetadata)
def get_evaluation_framework() -> AnswerEvaluationFrameworkMetadata:
    return evaluation_engine.framework_metadata()


@router.get("/interviews/evaluations/recent", response_model=list[dict[str, Any]])
def get_recent_evaluations(
    resume_id: UUID | None = None,
    session_id: str | None = None,
    limit: int = Query(default=10, ge=1, le=50),
) -> list[dict[str, Any]]:
    return repository.get_recent_answer_evaluations(
        resume_id=resume_id,
        session_id=session_id,
        limit=limit,
    )


@router.post("/interviews/orchestration/next", response_model=OrchestrationDecision)
def get_next_interview_action(payload: OrchestrationStateRequest) -> OrchestrationDecision:
    return orchestration_engine.decide_next(payload)


@router.post("/interviews/orchestration/summary", response_model=OrchestrationSummary)
def summarize_interview_session(payload: OrchestrationStateRequest) -> OrchestrationSummary:
    return orchestration_engine.summarize_session(payload)


@router.get("/interviews/orchestration/framework", response_model=OrchestrationFrameworkMetadata)
def get_orchestration_framework() -> OrchestrationFrameworkMetadata:
    return orchestration_engine.framework_metadata()


@router.get("/dashboard/{resume_id}", response_model=DashboardResponse)
def get_results_dashboard(
    resume_id: UUID,
    limit: int = Query(default=120, ge=10, le=500),
) -> DashboardResponse:
    parsed = repository.get_parsed_resume(resume_id)
    if not parsed:
        raise HTTPException(status_code=404, detail="Parsed resume not found")

    profile = parsed.get("profile") or {}
    evaluations = repository.get_recent_answer_evaluations(resume_id=resume_id, limit=limit)

    scoring_bands = [
        DashboardScoringBand(label="beginner", min_score=0.0, max_score=54.9, meaning="Core concepts are emerging; focus on fundamentals and structured answers."),
        DashboardScoringBand(label="intermediate", min_score=55.0, max_score=77.9, meaning="Solid baseline; deepen tradeoffs, edge cases, and production details."),
        DashboardScoringBand(label="ready", min_score=78.0, max_score=100.0, meaning="Interview-ready performance with consistent reasoning and communication."),
    ]

    breakdown: list[DashboardQuestionBreakdownItem] = []
    session_accumulator: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"scores": [], "weak_count": 0, "last_ts": "", "question_count": 0}
    )
    topic_scores: dict[str, list[float]] = defaultdict(list)
    weak_topic_accumulator: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"scores": [], "frequency": 0, "evidence": []}
    )

    for item in evaluations:
        response = item.get("response") or {}
        question = str(response.get("question") or item.get("question") or "Interview question")
        topic = str(response.get("focus_topic") or item.get("focus_topic") or "general")
        score_100 = float(response.get("weighted_final_score_100") or item.get("weighted_final_score_100") or 0.0)
        verdict = str(response.get("verdict") or item.get("verdict") or "weak")
        missed_key_points = list(response.get("missed_key_points") or item.get("missed_key_points") or [])
        coaching = str(response.get("better_answer_coaching") or "Add one clear tradeoff and one measurable validation metric.")
        session_id = str(item.get("session_id") or "session-unknown")
        created_at = str(item.get("created_at") or "")
        is_weak = bool(item.get("weak") or score_100 < 65.0)

        breakdown.append(
            DashboardQuestionBreakdownItem(
                evaluation_id=str(item.get("id") or ""),
                session_id=session_id,
                question_id=str(item.get("question_id") or "") or None,
                question=question,
                topic=topic,
                score_100=round(score_100, 1),
                verdict=verdict,
                is_weak=is_weak,
                missed_key_points=missed_key_points,
                coaching=coaching,
                created_at=created_at,
            )
        )

        bucket = session_accumulator[session_id]
        bucket["scores"].append(score_100)
        bucket["question_count"] += 1
        if is_weak:
            bucket["weak_count"] += 1
        if created_at and created_at > bucket["last_ts"]:
            bucket["last_ts"] = created_at

        topic_scores[topic].append(score_100)

        if is_weak:
            weak_bucket = weak_topic_accumulator[topic]
            weak_bucket["scores"].append(score_100)
            weak_bucket["frequency"] += 1
            weak_bucket["evidence"].extend(missed_key_points[:2])

    session_summary: list[DashboardSessionSummaryItem] = []
    for session_id, aggregate in session_accumulator.items():
        avg_score = sum(aggregate["scores"]) / max(1, len(aggregate["scores"]))
        readiness = max(0.0, min(100.0, avg_score - min(18.0, aggregate["weak_count"] * 2.5)))
        session_summary.append(
            DashboardSessionSummaryItem(
                session_id=session_id,
                completed_at=aggregate["last_ts"] or "",
                question_count=int(aggregate["question_count"]),
                avg_score_100=round(avg_score, 1),
                readiness_score_100=round(readiness, 1),
                readiness_band=_readiness_band(readiness),
                weak_area_count=int(aggregate["weak_count"]),
            )
        )

    session_summary.sort(key=lambda item: item.completed_at, reverse=True)

    latest_readiness = session_summary[0].readiness_score_100 if session_summary else round(
        float(parsed.get("quality", {}).get("overall_confidence", 0.0)) * 100.0,
        1,
    )

    trend = [
        DashboardTrendPoint(
            session_id=item.session_id,
            completed_at=item.completed_at,
            readiness_score_100=item.readiness_score_100,
            avg_score_100=item.avg_score_100,
        )
        for item in reversed(session_summary)
    ]

    radar = _build_skill_radar(profile=profile, topic_scores=topic_scores)

    weak_areas: list[DashboardWeakAreaItem] = []
    for topic, aggregate in weak_topic_accumulator.items():
        avg_score = sum(aggregate["scores"]) / max(1, len(aggregate["scores"]))
        weak_areas.append(
            DashboardWeakAreaItem(
                topic=topic,
                severity=_severity_from_score(avg_score),
                avg_score_100=round(avg_score, 1),
                frequency=int(aggregate["frequency"]),
                evidence_points=list(dict.fromkeys(aggregate["evidence"]))[:4],
            )
        )

    weak_areas.sort(
        key=lambda item: (
            0 if item.severity == "critical" else 1 if item.severity == "high" else 2,
            -item.frequency,
            item.avg_score_100,
        )
    )

    study_plan = _build_study_plan(weak_areas)

    target_role = "Backend Engineer"
    if evaluations:
        latest_response = evaluations[0].get("response") or {}
        latest_request = evaluations[0].get("request") or {}
        target_role = str(latest_response.get("target_role") or latest_request.get("target_role") or target_role)

    return DashboardResponse(
        resume_id=resume_id,
        candidate_name=str(profile.get("candidate_name") or "Candidate"),
        target_role=target_role,
        readiness_score_100=round(latest_readiness, 1),
        readiness_band=_readiness_band(latest_readiness),
        scoring_bands=scoring_bands,
        session_summary=session_summary,
        skill_radar=radar,
        question_breakdown=breakdown,
        weak_areas=weak_areas,
        trend=trend,
        recommended_study_plan=study_plan,
        feedback_templates=_feedback_templates(),
    )


def _readiness_band(score_100: float) -> str:
    if score_100 < 55.0:
        return "beginner"
    if score_100 < 78.0:
        return "intermediate"
    return "ready"


def _severity_from_score(score_100: float) -> str:
    if score_100 < 45.0:
        return "critical"
    if score_100 < 60.0:
        return "high"
    return "moderate"


def _build_skill_radar(*, profile: dict[str, Any], topic_scores: dict[str, list[float]]) -> DashboardRadarData:
    labels: list[str] = []
    values: list[float] = []

    skills = profile.get("skills") or []
    for skill in skills[:6]:
        if not isinstance(skill, dict):
            continue

        name = str(skill.get("canonical") or skill.get("raw") or "").strip()
        if not name:
            continue

        parser_score = float(skill.get("confidence", {}).get("score", 0.0)) * 100.0

        topic_match_scores: list[float] = []
        name_lower = name.lower()
        for topic, scores in topic_scores.items():
            topic_lower = topic.lower()
            if name_lower in topic_lower or topic_lower in name_lower:
                topic_match_scores.extend(scores)

        if topic_match_scores:
            topic_score = sum(topic_match_scores) / max(1, len(topic_match_scores))
            combined = (parser_score * 0.55) + (topic_score * 0.45)
        else:
            combined = parser_score

        labels.append(name)
        values.append(round(max(0.0, min(100.0, combined)), 1))

    if not labels:
        for topic, scores in list(topic_scores.items())[:6]:
            labels.append(topic)
            values.append(round(sum(scores) / max(1, len(scores)), 1))

    if not labels:
        return DashboardRadarData(labels=["Fundamentals", "Reasoning", "Clarity"], values=[45.0, 45.0, 45.0])

    return DashboardRadarData(labels=labels, values=values)


def _build_study_plan(weak_areas: list[DashboardWeakAreaItem]) -> list[DashboardStudyPlanItem]:
    if not weak_areas:
        return [
            DashboardStudyPlanItem(
                priority="P3",
                title="Maintain interview readiness",
                action="Run one mixed mock interview this week and review your strongest answer for consistency.",
                rationale="No critical weak areas detected in recent sessions.",
                estimated_days=5,
            )
        ]

    priorities = ["P1", "P2", "P3"]
    plan: list[DashboardStudyPlanItem] = []
    for index, area in enumerate(weak_areas[:3]):
        priority = priorities[min(index, len(priorities) - 1)]
        plan.append(
            DashboardStudyPlanItem(
                priority=priority,
                title=f"Improve {area.topic}",
                action=(
                    "Complete two focused drills: first answer in 4 minutes, second answer in 2 minutes with explicit tradeoffs and one metric."
                ),
                rationale=f"{area.frequency} weak signals and average score {area.avg_score_100:.1f}/100.",
                estimated_days=4 if priority == "P1" else 6 if priority == "P2" else 8,
            )
        )

    return plan


def _feedback_templates() -> list[str]:
    return [
        "Open with one-line architecture summary before details.",
        "State one explicit tradeoff and why you accepted it.",
        "Add one failure mode and mitigation to every design answer.",
        "Anchor your reasoning with one metric to validate success.",
        "Use assumptions first, then approach, then validation.",
        "Compare at least two alternatives before picking one.",
        "Mention rollout safety: canary, monitoring, rollback trigger.",
        "Reduce vague wording by naming specific components and flows.",
        "For debugging questions, rank hypotheses before deep diving.",
        "Close with what you would improve in the next iteration.",
    ]


def _run_parse_job(parse_job_id: UUID, resume_id: UUID) -> None:
    try:
        repository.update_parse_job(parse_job_id, status="running", progress=15, stage="text_extraction")

        resume = repository.get_resume(resume_id)
        if not resume:
            raise RuntimeError("resume_not_found")

        file_path = Path(resume["file_path"])
        file_type = str(resume["file_type"])

        repository.update_parse_job(parse_job_id, status="running", progress=45, stage="section_detection")

        parsed = pipeline.parse_resume(resume_id=resume_id, file_path=file_path, file_type=file_type)

        repository.update_parse_job(parse_job_id, status="running", progress=85, stage="entity_extraction")

        final_status = "needs_review" if parsed.status == "needs_review" else "parsed"
        repository.save_parsed_resume(resume_id, parsed.model_dump(mode="json"), final_status)
        repository.update_resume_status(resume_id, final_status)

        repository.update_parse_job(parse_job_id, status="completed", progress=100, stage="completed")
    except Exception as exc:
        repository.update_resume_status(resume_id, "failed")
        repository.update_parse_job(
            parse_job_id,
            status="failed",
            progress=100,
            stage="failed",
            error=str(exc),
        )


def _apply_json_path_update(payload: dict[str, Any], path: str, value: Any) -> None:
    tokens = _json_path_tokens(path)
    if not tokens:
        raise HTTPException(status_code=400, detail=f"Invalid correction path: {path}")

    current: Any = payload
    for token in tokens[:-1]:
        if isinstance(token, int):
            if not isinstance(current, list) or token >= len(current):
                raise HTTPException(status_code=400, detail=f"Invalid correction path: {path}")
            current = current[token]
        else:
            if not isinstance(current, dict) or token not in current:
                raise HTTPException(status_code=400, detail=f"Invalid correction path: {path}")
            current = current[token]

    last = tokens[-1]
    if isinstance(last, int):
        if not isinstance(current, list) or last >= len(current):
            raise HTTPException(status_code=400, detail=f"Invalid correction path: {path}")
        current[last] = value
    else:
        if not isinstance(current, dict):
            raise HTTPException(status_code=400, detail=f"Invalid correction path: {path}")
        current[last] = value


def _json_path_tokens(path: str) -> list[str | int]:
    tokens: list[str | int] = []
    for part in path.split("."):
        if not part:
            return []
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)", part)
        if not match:
            return []
        tokens.append(match.group(1))
        rest = part[match.end() :]
        while rest:
            index_match = re.match(r"^\[(\d+)\]", rest)
            if not index_match:
                return []
            tokens.append(int(index_match.group(1)))
            rest = rest[index_match.end() :]
    return tokens
