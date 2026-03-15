from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from .schemas import (
    AdaptiveFollowUp,
    QuestionGenerationRequest,
    QuestionGenerationResponse,
    QuestionObject,
    QuestionValidationRule,
)

_MIN_PROMPT_WORDS = 11
_MAX_GENERIC_PHRASE_RATIO = 0.18
_DUPLICATE_SIMILARITY_THRESHOLD = 0.84

_CATEGORY_SEQUENCE = [
    "fundamentals",
    "project_deep_dive",
    "role_specific_stack",
    "debugging_scenario",
]

_GENERIC_PATTERNS = (
    "what is",
    "define",
    "explain the difference",
    "tell me about",
    "advantages and disadvantages",
)


PROMPT_TEMPLATES: dict[str, str] = {
    "system_generation": (
        "You are an expert technical interviewer. Generate practical, role-relevant questions. "
        "Avoid trivia and generic textbook prompts. Every question must tie to the candidate profile, "
        "target role, focus topics, and previous weaknesses."
    ),
    "user_generation": (
        "Candidate profile JSON:\n{candidate_profile_json}\n\n"
        "Target role: {target_role}\n"
        "Experience level: {experience_level}\n"
        "Focus topics: {focus_topics}\n"
        "Previous weaknesses: {previous_weaknesses}\n"
        "Question count: {question_count}\n\n"
        "Generate a balanced set across: fundamentals, project_deep_dive, role_specific_stack, debugging_scenario. "
        "For each question include: difficulty(1-5), expected_time_minutes, ideal_answer_checklist, adaptive_follow_ups. "
        "Return valid JSON only using the provided question object schema."
    ),
    "user_regeneration": (
        "Previous output quality is below threshold. Improve specificity and remove duplicates.\n"
        "Low-quality question IDs: {low_quality_ids}\n"
        "Quality issues: {quality_issues}\n"
        "Preserve category balance and regenerate only flagged questions.\n"
        "Return valid JSON only."
    ),
}


VALIDATION_RULES: list[QuestionValidationRule] = [
    QuestionValidationRule(
        rule_id="category-balance",
        description="Each batch must cover fundamentals, project_deep_dive, role_specific_stack, and debugging_scenario.",
    ),
    QuestionValidationRule(
        rule_id="prompt-specificity",
        description="Prompt must include context, constraints, and expected tradeoff discussion; avoid generic textbook wording.",
    ),
    QuestionValidationRule(
        rule_id="no-near-duplicates",
        description="Prompt similarity across the batch must remain below threshold to avoid repeated questions.",
    ),
    QuestionValidationRule(
        rule_id="checklist-completeness",
        description="Ideal answer checklist must include architecture, tradeoffs, and validation/testing elements.",
    ),
    QuestionValidationRule(
        rule_id="difficulty-time-alignment",
        description="Expected time must increase with difficulty and scenario complexity.",
    ),
]


@dataclass
class ValidationIssue:
    question_id: str
    reason: str


class QuestionGenerationEngine:
    def generate(self, request: QuestionGenerationRequest) -> QuestionGenerationResponse:
        profile = request.candidate_profile or {}
        targets = self._derive_topic_pool(request, profile)

        questions: list[QuestionObject] = []
        desired = request.question_count

        for index in range(desired):
            category = _CATEGORY_SEQUENCE[index % len(_CATEGORY_SEQUENCE)]
            topic = targets[index % len(targets)]
            question = self._build_question(index=index, category=category, topic=topic, request=request, profile=profile)
            questions.append(question)

        issues = self._validate_questions(questions)
        if issues:
            lowered = {issue.question_id for issue in issues}
            questions = self._regenerate_flagged(questions, lowered, request, profile)
            issues = self._validate_questions(questions)

        quality = round(sum(item.quality_score for item in questions) / max(1, len(questions)), 3)
        warnings = [f"{issue.question_id}: {issue.reason}" for issue in issues]

        return QuestionGenerationResponse(
            target_role=request.target_role,
            experience_level=request.experience_level,
            generated_count=len(questions),
            questions=questions,
            overall_quality_score=quality,
            warnings=warnings,
        )

    def framework_metadata(self) -> dict[str, Any]:
        example_question_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "QuestionObject",
            "type": "object",
            "required": [
                "question_id",
                "category",
                "prompt",
                "focus_topic",
                "difficulty",
                "expected_time_minutes",
                "ideal_answer_checklist",
                "adaptive_follow_ups",
                "quality_score",
            ],
            "properties": {
                "question_id": {"type": "string", "pattern": "^Q[0-9]{2}$"},
                "category": {
                    "type": "string",
                    "enum": [
                        "fundamentals",
                        "project_deep_dive",
                        "role_specific_stack",
                        "debugging_scenario",
                    ],
                },
                "prompt": {"type": "string", "minLength": 40},
                "focus_topic": {"type": "string", "minLength": 2},
                "difficulty": {"type": "integer", "minimum": 1, "maximum": 5},
                "expected_time_minutes": {"type": "integer", "minimum": 3, "maximum": 30},
                "ideal_answer_checklist": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 8,
                    "items": {"type": "string", "minLength": 5},
                },
                "adaptive_follow_ups": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["trigger", "follow_up_prompt", "intent"],
                        "properties": {
                            "trigger": {"type": "string"},
                            "follow_up_prompt": {"type": "string"},
                            "intent": {"type": "string"},
                        },
                    },
                },
                "quality_score": {"type": "number", "minimum": 0, "maximum": 1},
            },
        }

        return {
            "prompt_templates": PROMPT_TEMPLATES,
            "json_schema": example_question_schema,
            "validation_rules": [rule.model_dump() for rule in VALIDATION_RULES],
            "regeneration_strategy": {
                "when_to_regenerate": "Regenerate when overall_quality_score < 0.78 or any question quality_score < 0.62 or duplicates are detected.",
                "actions": [
                    "Identify low-quality or duplicate questions by question_id.",
                    "Retain high-quality questions and regenerate only flagged questions.",
                    "Force regenerated prompts to include candidate project or weakness context.",
                    "Increase checklist depth by adding tradeoffs and measurable outcomes.",
                    "Re-run validation and cap retries to 2 rounds.",
                ],
            },
        }

    def render_generation_prompt(self, request: QuestionGenerationRequest) -> dict[str, str]:
        payload = request.model_dump()
        profile = payload.get("candidate_profile") or {}
        return {
            "system": PROMPT_TEMPLATES["system_generation"],
            "user": PROMPT_TEMPLATES["user_generation"].format(
                candidate_profile_json=json.dumps(profile, ensure_ascii=True, indent=2),
                target_role=request.target_role,
                experience_level=request.experience_level,
                focus_topics=", ".join(request.focus_topics) or "None",
                previous_weaknesses=", ".join(request.previous_session_weaknesses) or "None",
                question_count=request.question_count,
            ),
        }

    def _derive_topic_pool(self, request: QuestionGenerationRequest, profile: dict[str, Any]) -> list[str]:
        pool: list[str] = []

        for topic in request.focus_topics:
            normalized = topic.strip()
            if normalized:
                pool.append(normalized)

        for weakness in request.previous_session_weaknesses:
            normalized = weakness.strip()
            if normalized and normalized not in pool:
                pool.append(normalized)

        for skill in profile.get("skills", [])[:8]:
            canonical = ""
            if isinstance(skill, dict):
                canonical = (skill.get("canonical") or skill.get("raw") or "").strip()
            if canonical and canonical not in pool:
                pool.append(canonical)

        for project in profile.get("projects", [])[:4]:
            if not isinstance(project, dict):
                continue
            name = (project.get("name") or "").strip()
            if name and name not in pool:
                pool.append(name)

        if request.target_role not in pool:
            pool.append(request.target_role)

        if not pool:
            return ["APIs", "Data modeling", "Reliability", request.target_role]

        return pool

    def _build_question(
        self,
        *,
        index: int,
        category: str,
        topic: str,
        request: QuestionGenerationRequest,
        profile: dict[str, Any],
    ) -> QuestionObject:
        difficulty = self._pick_difficulty(category, request.experience_level, index)
        expected_time = self._expected_time_for(difficulty, category)
        prompt = self._build_prompt(category, topic, request.target_role, profile)
        checklist = self._build_checklist(category, topic)
        follow_ups = self._build_follow_ups(category, topic, request.target_role)
        score = self._score_quality(prompt=prompt, checklist=checklist, follow_ups=follow_ups)

        return QuestionObject(
            question_id=f"Q{index + 1:02d}",
            category=category,
            prompt=prompt,
            focus_topic=topic,
            difficulty=difficulty,
            expected_time_minutes=expected_time,
            ideal_answer_checklist=checklist,
            adaptive_follow_ups=follow_ups,
            quality_score=score,
        )

    def _build_prompt(self, category: str, topic: str, target_role: str, profile: dict[str, Any]) -> str:
        project_names = [
            item.get("name", "")
            for item in profile.get("projects", [])
            if isinstance(item, dict) and item.get("name")
        ]
        project_hint = project_names[0] if project_names else "a relevant project"

        if category == "fundamentals":
            return (
                f"For a {target_role} role, explain the core principles behind {topic}. "
                "Then show how you would choose between two implementation options under latency and maintainability constraints."
            )

        if category == "project_deep_dive":
            return (
                f"Pick {project_hint} from your experience and walk through a deep technical decision around {topic}. "
                "Describe architecture, tradeoffs, failure modes, and what you would improve in the next iteration."
            )

        if category == "role_specific_stack":
            return (
                f"You are building a production feature in the {target_role} stack involving {topic}. "
                "Design the implementation plan, data model, testing strategy, and rollout approach with observability metrics."
            )

        return (
            f"A production incident is reported in a {target_role} system touching {topic}. "
            "Debug the issue step-by-step, including hypothesis ranking, instrumentation checks, root-cause confirmation, and prevention."
        )

    def _build_checklist(self, category: str, topic: str) -> list[str]:
        checklist = [
            f"Explains core concept of {topic} with precise terminology",
            "States assumptions and constraints before proposing a solution",
            "Compares at least two alternatives with clear tradeoffs",
            "Defines testing or validation approach",
        ]

        if category in {"project_deep_dive", "debugging_scenario"}:
            checklist.append("Includes concrete production-style failure handling")

        if category == "role_specific_stack":
            checklist.append("Covers deployment, monitoring, and rollback signals")

        if category == "debugging_scenario":
            checklist.append("Ranks hypotheses and converges with evidence")

        return checklist[:8]

    def _build_follow_ups(self, category: str, topic: str, target_role: str) -> list[AdaptiveFollowUp]:
        return [
            AdaptiveFollowUp(
                trigger="Answer lacks measurable success criteria",
                follow_up_prompt=(
                    f"Add two concrete metrics you would track to verify that your {topic} solution works in production."
                ),
                intent="Push for operational rigor",
            ),
            AdaptiveFollowUp(
                trigger="Answer is high-level but misses tradeoffs",
                follow_up_prompt=(
                    f"For this {target_role} scenario, what downside did your chosen design introduce, and how would you mitigate it?"
                ),
                intent="Assess depth of engineering judgment",
            ),
            AdaptiveFollowUp(
                trigger="Answer mentions tools without sequencing",
                follow_up_prompt="Walk through the implementation sequence from day 1 to production launch.",
                intent="Validate execution thinking",
            ),
        ]

    def _pick_difficulty(self, category: str, level: str, index: int) -> int:
        base_by_level = {"junior": 2, "mid": 3, "senior": 4, "staff": 5}
        base = base_by_level.get(level, 3)

        if category == "fundamentals":
            adjustment = -1
        elif category == "debugging_scenario":
            adjustment = 1
        else:
            adjustment = 0

        if index % 4 == 3:
            adjustment += 1

        return max(1, min(5, base + adjustment))

    def _expected_time_for(self, difficulty: int, category: str) -> int:
        baseline = {1: 6, 2: 8, 3: 11, 4: 14, 5: 18}[difficulty]
        if category == "project_deep_dive":
            baseline += 2
        if category == "debugging_scenario":
            baseline += 1
        return max(3, min(30, baseline))

    def _score_quality(self, *, prompt: str, checklist: list[str], follow_ups: list[AdaptiveFollowUp]) -> float:
        words = len(prompt.split())
        prompt_ok = 1.0 if words >= _MIN_PROMPT_WORDS else 0.45

        generic_hits = sum(1 for token in _GENERIC_PATTERNS if token in prompt.lower())
        generic_penalty = min(1.0, generic_hits * _MAX_GENERIC_PHRASE_RATIO)

        checklist_score = min(1.0, len(checklist) / 5)
        followup_score = min(1.0, len(follow_ups) / 2)

        score = (prompt_ok * 0.4) + (checklist_score * 0.35) + (followup_score * 0.3) - (generic_penalty * 0.2)
        return round(max(0.0, min(1.0, score)), 3)

    def _validate_questions(self, questions: list[QuestionObject]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        seen_categories = {item.category for item in questions}
        for category in _CATEGORY_SEQUENCE:
            if category not in seen_categories:
                issues.append(ValidationIssue(question_id="BATCH", reason=f"Missing category: {category}"))

        for idx, item in enumerate(questions):
            if len(item.prompt.split()) < _MIN_PROMPT_WORDS:
                issues.append(ValidationIssue(question_id=item.question_id, reason="Prompt too short"))
            if len(item.ideal_answer_checklist) < 3:
                issues.append(ValidationIssue(question_id=item.question_id, reason="Checklist too small"))
            if item.quality_score < 0.62:
                issues.append(ValidationIssue(question_id=item.question_id, reason="Low quality score"))

            for prior in questions[:idx]:
                similarity = SequenceMatcher(None, item.prompt.lower(), prior.prompt.lower()).ratio()
                if similarity >= _DUPLICATE_SIMILARITY_THRESHOLD:
                    issues.append(
                        ValidationIssue(
                            question_id=item.question_id,
                            reason=f"Near-duplicate with {prior.question_id} (similarity {similarity:.2f})",
                        )
                    )
                    break

        return issues

    def _regenerate_flagged(
        self,
        questions: list[QuestionObject],
        flagged_ids: set[str],
        request: QuestionGenerationRequest,
        profile: dict[str, Any],
    ) -> list[QuestionObject]:
        regenerated: list[QuestionObject] = []
        topic_pool = self._derive_topic_pool(request, profile)
        extra_offset = 3

        for index, question in enumerate(questions):
            if question.question_id not in flagged_ids:
                regenerated.append(question)
                continue

            topic = topic_pool[(index + extra_offset) % len(topic_pool)]
            replacement = self._build_question(
                index=index,
                category=question.category,
                topic=topic,
                request=request,
                profile=profile,
            )
            replacement.prompt = (
                replacement.prompt
                + " Include one concrete metric and one failure-mode mitigation in your answer."
            )
            replacement.quality_score = self._score_quality(
                prompt=replacement.prompt,
                checklist=replacement.ideal_answer_checklist,
                follow_ups=replacement.adaptive_follow_ups,
            )
            regenerated.append(replacement)

        return regenerated


question_engine = QuestionGenerationEngine()
