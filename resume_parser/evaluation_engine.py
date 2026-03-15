from __future__ import annotations

import json
import re
from typing import Any

from .schemas import (
    AnswerEvaluationFrameworkMetadata,
    AnswerEvaluationRequest,
    AnswerEvaluationResponse,
    CriterionScore,
    EvidenceSnippet,
    RubricCriterionDefinition,
    WorkedEvaluationExample,
)

_FORMULA_VERSION = "v1"

RUBRIC_TABLE: list[RubricCriterionDefinition] = [
    RubricCriterionDefinition(
        criterion="correctness",
        score_min=0,
        score_max=5,
        weight=0.32,
        scoring_guide=[
            "0: Factually incorrect or unrelated answer",
            "1: Major errors with limited relevant content",
            "2: Partially correct but misses core mechanics",
            "3: Mostly correct with minor issues",
            "4: Correct and technically sound",
            "5: Fully correct with precise detail",
        ],
    ),
    RubricCriterionDefinition(
        criterion="depth",
        score_min=0,
        score_max=5,
        weight=0.23,
        scoring_guide=[
            "0: Superficial and generic",
            "1: Very shallow explanation",
            "2: Some details but incomplete depth",
            "3: Reasonable detail with gaps",
            "4: Deep and practical details",
            "5: Excellent depth with production realism",
        ],
    ),
    RubricCriterionDefinition(
        criterion="reasoning_tradeoffs",
        score_min=0,
        score_max=5,
        weight=0.20,
        scoring_guide=[
            "0: No reasoning presented",
            "1: Weak rationale without alternatives",
            "2: Basic rationale with little tradeoff analysis",
            "3: Clear reasoning and one tradeoff",
            "4: Multiple tradeoffs and clear choice logic",
            "5: Strong comparative reasoning and mitigation paths",
        ],
    ),
    RubricCriterionDefinition(
        criterion="clarity_communication",
        score_min=0,
        score_max=5,
        weight=0.15,
        scoring_guide=[
            "0: Incoherent",
            "1: Hard to follow",
            "2: Partially clear",
            "3: Clear with some structure",
            "4: Well structured and concise",
            "5: Excellent clarity and communication",
        ],
    ),
    RubricCriterionDefinition(
        criterion="confidence_signal",
        score_min=0,
        score_max=5,
        weight=0.10,
        scoring_guide=[
            "0: Very uncertain, mostly hedged",
            "1: Highly tentative",
            "2: Mixed confidence",
            "3: Moderately confident",
            "4: Confident with justified statements",
            "5: Highly confident and grounded",
        ],
    ),
]

PROMPT_TEMPLATES: dict[str, str] = {
    "system_evaluation": (
        "You are a strict technical interview evaluator. Score using rubric only. "
        "Do not invent facts that are not in candidate answer. "
        "Return only valid JSON with no markdown, no extra keys, and no prose outside JSON."
    ),
    "user_evaluation": (
        "Question: {question}\n"
        "Target role: {target_role}\n"
        "Experience level: {experience_level}\n"
        "Focus topic: {focus_topic}\n"
        "Difficulty: {difficulty}\n"
        "Ideal answer checklist: {ideal_answer_checklist_json}\n"
        "Candidate answer: {candidate_answer}\n\n"
        "Evaluate criteria: correctness, depth, reasoning/trade-offs, clarity/communication, confidence (infer only if answer indicates it).\n"
        "Rules:\n"
        "- Use strict rubric scoring 0-5.\n"
        "- Evidence snippets must be exact quotes from candidate answer.\n"
        "- Include missed key points from checklist.\n"
        "- Add short better-answer coaching.\n"
        "- Return only valid JSON matching schema."
    ),
}


class AnswerEvaluationEngine:
    def evaluate(self, request: AnswerEvaluationRequest) -> AnswerEvaluationResponse:
        answer = request.candidate_answer.strip()
        checklist = request.ideal_answer_checklist or self._fallback_checklist(request.question, request.focus_topic)

        if request.skipped:
            coaching = "Do not skip. Start with a concise baseline approach, then add one tradeoff and one metric."
            follow_ups = [
                "Give a 60-second baseline solution before diving into details.",
                "Name one tradeoff in your chosen approach.",
                "State one metric you would monitor after deployment.",
            ]
            return AnswerEvaluationResponse(
                question=request.question,
                target_role=request.target_role,
                experience_level=request.experience_level,
                focus_topic=request.focus_topic,
                difficulty=request.difficulty,
                correctness=CriterionScore(value=0, rationale="Skipped answer provides no correctness evidence."),
                depth=CriterionScore(value=0, rationale="Skipped answer provides no depth evidence."),
                reasoning_tradeoffs=CriterionScore(value=0, rationale="Skipped answer provides no reasoning evidence."),
                clarity_communication=CriterionScore(value=1, rationale="Short but non-informative response."),
                confidence_signal=CriterionScore(value=0, rationale="Skipping indicates no confidence signal."),
                weighted_final_score_100=3.0,
                weighted_final_score_10=0.3,
                verdict="weak",
                confidence_in_score=0.95,
                evidence_snippets=[],
                missed_key_points=checklist[:4],
                adaptive_follow_up_prompts=follow_ups,
                better_answer_coaching=coaching,
                formula_version=_FORMULA_VERSION,
                warnings=["Candidate skipped the question."],
                score=0.03,
                feedback="Answer was skipped; provide at least a baseline technical approach.",
                weak=True,
            )

        correctness_score, matched_count, missed_points = self._score_correctness(answer, checklist)
        depth_score = self._score_depth(answer)
        reasoning_score = self._score_reasoning(answer)
        clarity_score = self._score_clarity(answer)
        confidence_score = self._score_confidence(answer)

        correctness = CriterionScore(
            value=correctness_score,
            rationale=(
                f"Matched {matched_count} of {len(checklist)} key checklist points." if checklist else "Scored from technical relevance and factual precision signals."
            ),
        )
        depth = CriterionScore(
            value=depth_score,
            rationale="Depth is scored from detail level, specificity, and production-oriented language.",
        )
        reasoning_tradeoffs = CriterionScore(
            value=reasoning_score,
            rationale="Reasoning score reflects alternatives, tradeoffs, and mitigation logic.",
        )
        clarity_communication = CriterionScore(
            value=clarity_score,
            rationale="Clarity score is based on structure, readability, and coherent sequencing.",
        )
        confidence_signal = CriterionScore(
            value=confidence_score,
            rationale="Confidence score is inferred from assertive versus hedged language in the answer.",
        )

        evidence_snippets = self._build_evidence_snippets(answer)
        warnings: list[str] = []
        validated_snippets: list[EvidenceSnippet] = []
        lower_answer = answer.lower()
        for snippet in evidence_snippets:
            if snippet.quote.lower() in lower_answer:
                validated_snippets.append(snippet)
            else:
                warnings.append(f"Dropped non-verifiable evidence snippet for {snippet.criterion}")

        weighted_final_score_100, weighted_final_score_10 = self._compute_weighted_scores(
            correctness=correctness.value,
            depth=depth.value,
            reasoning_tradeoffs=reasoning_tradeoffs.value,
            clarity_communication=clarity_communication.value,
            confidence_signal=confidence_signal.value,
        )
        verdict = self._verdict_from_score(weighted_final_score_100)

        confidence_in_score = self._confidence_in_score(answer=answer, snippet_count=len(validated_snippets))
        better_answer_coaching = self._build_coaching(missed_points, reasoning_tradeoffs.value, depth.value)
        adaptive_follow_ups = self._build_adaptive_follow_ups(
            missed_points=missed_points,
            correctness=correctness.value,
            depth=depth.value,
            reasoning=reasoning_tradeoffs.value,
        )

        weak = weighted_final_score_100 < 60.0
        feedback = (
            f"Overall {weighted_final_score_100:.1f}/100. "
            f"Top gap: {missed_points[0] if missed_points else 'add deeper tradeoff analysis and concrete evidence.'}"
        )

        return AnswerEvaluationResponse(
            question=request.question,
            target_role=request.target_role,
            experience_level=request.experience_level,
            focus_topic=request.focus_topic,
            difficulty=request.difficulty,
            correctness=correctness,
            depth=depth,
            reasoning_tradeoffs=reasoning_tradeoffs,
            clarity_communication=clarity_communication,
            confidence_signal=confidence_signal,
            weighted_final_score_100=weighted_final_score_100,
            weighted_final_score_10=weighted_final_score_10,
            verdict=verdict,
            confidence_in_score=confidence_in_score,
            evidence_snippets=validated_snippets,
            missed_key_points=missed_points,
            adaptive_follow_up_prompts=adaptive_follow_ups,
            better_answer_coaching=better_answer_coaching,
            formula_version=_FORMULA_VERSION,
            warnings=warnings,
            score=round(weighted_final_score_100 / 100, 3),
            feedback=feedback,
            weak=weak,
        )

    def framework_metadata(self) -> AnswerEvaluationFrameworkMetadata:
        return AnswerEvaluationFrameworkMetadata(
            rubric_table=RUBRIC_TABLE,
            evaluation_prompt_templates=PROMPT_TEMPLATES,
            json_schema=self._output_json_schema(),
            post_processing_formula=(
                "final_score_5 = sum(criteria_score_i * weight_i); "
                "weighted_final_score_100 = round((final_score_5 / 5) * 100, 1); "
                "weighted_final_score_10 = round(weighted_final_score_100 / 10, 2)"
            ),
            calibration_strategy=[
                "Use a fixed anchor set of scored answers per role and level; compare weekly model scores to anchor labels.",
                "Track mean absolute deviation per criterion and alert when drift exceeds 0.6 points on 0-5 scale.",
                "Run blind double-scoring on 10% samples and use adjudication notes to refresh rubric examples.",
                "Version prompts and formula; never mix scores across versions without normalization.",
                "Apply confidence gating: if confidence_in_score < 0.45, route to secondary evaluation pass.",
            ],
            worked_examples=self._worked_examples(),
        )

    def render_evaluation_prompt(self, request: AnswerEvaluationRequest) -> dict[str, str]:
        return {
            "system": PROMPT_TEMPLATES["system_evaluation"],
            "user": PROMPT_TEMPLATES["user_evaluation"].format(
                question=request.question,
                target_role=request.target_role,
                experience_level=request.experience_level,
                focus_topic=request.focus_topic or "general",
                difficulty=request.difficulty,
                ideal_answer_checklist_json=json.dumps(request.ideal_answer_checklist, ensure_ascii=True),
                candidate_answer=request.candidate_answer,
            ),
        }

    def _score_correctness(self, answer: str, checklist: list[str]) -> tuple[int, int, list[str]]:
        if not checklist:
            keyword_score = self._count_keywords(answer, ["correct", "because", "api", "database", "tradeoff"])
            return min(5, max(1, 2 + keyword_score)), 0, []

        answer_tokens = self._token_set(answer)
        matched = 0
        missed: list[str] = []

        for item in checklist:
            key_tokens = {token for token in self._token_set(item) if len(token) >= 4}
            hit = bool(key_tokens and answer_tokens.intersection(key_tokens))
            if hit:
                matched += 1
            else:
                missed.append(item)

        coverage = matched / max(1, len(checklist))
        if coverage >= 0.85:
            score = 5
        elif coverage >= 0.65:
            score = 4
        elif coverage >= 0.45:
            score = 3
        elif coverage >= 0.25:
            score = 2
        elif coverage > 0:
            score = 1
        else:
            score = 0

        return score, matched, missed

    def _score_depth(self, answer: str) -> int:
        word_count = len(answer.split())
        detail_markers = self._count_keywords(
            answer,
            ["because", "for example", "tradeoff", "latency", "throughput", "index", "cache", "rollback"],
        )

        if word_count >= 180:
            base = 4
        elif word_count >= 130:
            base = 3
        elif word_count >= 90:
            base = 2
        elif word_count >= 55:
            base = 1
        else:
            base = 0

        return max(0, min(5, base + min(1, detail_markers // 2)))

    def _score_reasoning(self, answer: str) -> int:
        markers = self._count_keywords(
            answer,
            ["tradeoff", "alternative", "instead", "risk", "mitigate", "if", "then", "therefore", "because"],
        )
        if markers >= 8:
            return 5
        if markers >= 6:
            return 4
        if markers >= 4:
            return 3
        if markers >= 2:
            return 2
        if markers >= 1:
            return 1
        return 0

    def _score_clarity(self, answer: str) -> int:
        sentences = self._sentences(answer)
        if not sentences:
            return 0

        avg_words = sum(len(sentence.split()) for sentence in sentences) / max(1, len(sentences))
        structure_markers = self._count_keywords(answer, ["first", "then", "finally", "next", "therefore"])

        score = 2
        if 8 <= avg_words <= 28:
            score += 1
        if len(sentences) >= 3:
            score += 1
        if structure_markers >= 2:
            score += 1

        return max(0, min(5, score))

    def _score_confidence(self, answer: str) -> int:
        assertive = self._count_keywords(answer, ["will", "must", "should", "i would", "we should"])
        hedged = self._count_keywords(answer, ["maybe", "probably", "might", "i think", "not sure"])

        score = 3 + min(2, assertive // 2) - min(3, hedged)
        return max(0, min(5, score))

    def _build_evidence_snippets(self, answer: str) -> list[EvidenceSnippet]:
        sentences = self._sentences(answer)
        if not sentences:
            return []

        snippets: list[EvidenceSnippet] = []
        criterion_markers = [
            ("correctness", ["api", "database", "cache", "queue", "index", "schema"]),
            ("depth", ["because", "for example", "latency", "throughput", "rollback"]),
            ("reasoning_tradeoffs", ["tradeoff", "alternative", "risk", "mitigate"]),
            ("clarity_communication", ["first", "then", "finally", "therefore"]),
            ("confidence_signal", ["i would", "must", "should", "maybe", "probably"]),
        ]

        for criterion, markers in criterion_markers:
            quote = self._find_sentence(sentences, markers)
            if not quote:
                continue
            snippets.append(
                EvidenceSnippet(
                    criterion=criterion,
                    quote=quote,
                    reason=f"Snippet indicates {criterion.replace('_', ' ')}",
                )
            )

        return snippets[:8]

    def _find_sentence(self, sentences: list[str], markers: list[str]) -> str | None:
        lower_markers = [item.lower() for item in markers]
        for sentence in sentences:
            lower = sentence.lower()
            if any(marker in lower for marker in lower_markers):
                return sentence[:240]
        return sentences[0][:240] if sentences else None

    def _compute_weighted_scores(
        self,
        *,
        correctness: int,
        depth: int,
        reasoning_tradeoffs: int,
        clarity_communication: int,
        confidence_signal: int,
    ) -> tuple[float, float]:
        weights = {item.criterion: item.weight for item in RUBRIC_TABLE}
        final_score_5 = (
            correctness * weights["correctness"]
            + depth * weights["depth"]
            + reasoning_tradeoffs * weights["reasoning_tradeoffs"]
            + clarity_communication * weights["clarity_communication"]
            + confidence_signal * weights["confidence_signal"]
        )
        score_100 = round((final_score_5 / 5.0) * 100.0, 1)
        score_10 = round(score_100 / 10.0, 2)
        return score_100, score_10

    def _verdict_from_score(self, score_100: float) -> str:
        if score_100 < 55:
            return "weak"
        if score_100 < 78:
            return "average"
        return "strong"

    def _confidence_in_score(self, *, answer: str, snippet_count: int) -> float:
        words = len(answer.split())
        coverage = min(1.0, words / 180)
        evidence_factor = min(1.0, snippet_count / 5)
        return round((coverage * 0.55) + (evidence_factor * 0.45), 3)

    def _build_coaching(self, missed_points: list[str], reasoning_score: int, depth_score: int) -> str:
        if missed_points:
            return (
                "Start with a clear structure, then explicitly cover this missed point: "
                f"{missed_points[0]}. Add one concrete metric and one tradeoff."[:280]
            )

        if reasoning_score <= 2:
            return "Improve by comparing at least two approaches, then justify your choice with risk and mitigation details."

        if depth_score <= 2:
            return "Add concrete implementation details, production constraints, and one real validation step to deepen your answer."

        return "Strong answer. To make it exceptional, add measurable success criteria and a brief rollback strategy."

    def _build_adaptive_follow_ups(
        self,
        *,
        missed_points: list[str],
        correctness: int,
        depth: int,
        reasoning: int,
    ) -> list[str]:
        prompts: list[str] = []

        if missed_points:
            prompts.append(f"Expand on this missing point: {missed_points[0]}")

        if correctness <= 2:
            prompts.append("Restate your core approach in concrete technical steps and include one validation check.")

        if depth <= 2:
            prompts.append("Add one production constraint and explain how your design handles it.")

        if reasoning <= 2:
            prompts.append("Compare one alternative approach and explain tradeoffs before final choice.")

        if not prompts:
            prompts.append("Provide one optimization and one rollback trigger for your proposed solution.")

        return prompts[:3]

    def _fallback_checklist(self, question: str, focus_topic: str | None) -> list[str]:
        topic = (focus_topic or "the topic").strip() or "the topic"
        return [
            f"Correctly explains core concept(s) relevant to {topic}",
            "States assumptions and constraints clearly",
            "Discusses at least one tradeoff",
            "Describes validation or testing approach",
            f"Connects answer directly to the asked question: {question[:80]}",
        ]

    def _count_keywords(self, text: str, keywords: list[str]) -> int:
        lower = text.lower()
        return sum(1 for key in keywords if key in lower)

    def _token_set(self, text: str) -> set[str]:
        return {token for token in re.findall(r"[a-zA-Z0-9_]+", text.lower()) if token}

    def _sentences(self, text: str) -> list[str]:
        chunks = re.split(r"(?<=[.!?])\s+", text.strip())
        return [chunk.strip() for chunk in chunks if chunk.strip()]

    def _output_json_schema(self) -> dict[str, Any]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "AnswerEvaluationResponse",
            "type": "object",
            "required": [
                "question",
                "target_role",
                "experience_level",
                "difficulty",
                "correctness",
                "depth",
                "reasoning_tradeoffs",
                "clarity_communication",
                "confidence_signal",
                "weighted_final_score_100",
                "weighted_final_score_10",
                "verdict",
                "confidence_in_score",
                "evidence_snippets",
                "missed_key_points",
                "better_answer_coaching",
                "formula_version",
            ],
            "properties": {
                "question": {"type": "string"},
                "target_role": {"type": "string"},
                "experience_level": {"type": "string", "enum": ["junior", "mid", "senior", "staff"]},
                "focus_topic": {"type": ["string", "null"]},
                "difficulty": {"type": "integer", "minimum": 1, "maximum": 5},
                "correctness": {"$ref": "#/$defs/criterionScore"},
                "depth": {"$ref": "#/$defs/criterionScore"},
                "reasoning_tradeoffs": {"$ref": "#/$defs/criterionScore"},
                "clarity_communication": {"$ref": "#/$defs/criterionScore"},
                "confidence_signal": {"$ref": "#/$defs/criterionScore"},
                "weighted_final_score_100": {"type": "number", "minimum": 0, "maximum": 100},
                "weighted_final_score_10": {"type": "number", "minimum": 0, "maximum": 10},
                "verdict": {"type": "string", "enum": ["weak", "average", "strong"]},
                "confidence_in_score": {"type": "number", "minimum": 0, "maximum": 1},
                "evidence_snippets": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["criterion", "quote", "reason"],
                        "properties": {
                            "criterion": {"type": "string"},
                            "quote": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                    },
                },
                "missed_key_points": {"type": "array", "items": {"type": "string"}},
                "better_answer_coaching": {"type": "string", "maxLength": 280},
                "formula_version": {"type": "string"},
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
            "$defs": {
                "criterionScore": {
                    "type": "object",
                    "required": ["value", "rationale"],
                    "properties": {
                        "value": {"type": "integer", "minimum": 0, "maximum": 5},
                        "rationale": {"type": "string"},
                    },
                }
            },
        }

    def _worked_examples(self) -> list[WorkedEvaluationExample]:
        return [
            WorkedEvaluationExample(
                label="weak",
                question="How would you scale asynchronous parse jobs?",
                answer_excerpt="I would probably add more servers maybe and use caching. It should be fine.",
                summary="Low correctness and depth. Missing queue semantics, retries, and observability.",
            ),
            WorkedEvaluationExample(
                label="average",
                question="How would you scale asynchronous parse jobs?",
                answer_excerpt=(
                    "I would use Celery workers with Redis and add retry logic. I would monitor queue length and worker errors, "
                    "but I have not decided a dead-letter strategy yet."
                ),
                summary="Reasonable direction but limited tradeoff depth and incomplete failure-mode handling.",
            ),
            WorkedEvaluationExample(
                label="strong",
                question="How would you scale asynchronous parse jobs?",
                answer_excerpt=(
                    "I would separate fast and heavy queues, configure bounded retries with dead-letter routing, and autoscale workers "
                    "from queue lag plus throughput targets. If retry storms appear, I would add jittered backoff and circuit breaking."
                ),
                summary="Strong correctness, depth, tradeoffs, and production-level mitigation strategy.",
            ),
        ]


evaluation_engine = AnswerEvaluationEngine()
