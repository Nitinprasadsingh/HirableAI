from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .schemas import (
    OrchestrationDecision,
    OrchestrationFrameworkMetadata,
    OrchestrationPolicyScore,
    OrchestrationStateRequest,
    OrchestrationStopReason,
    OrchestrationSummary,
    OrchestrationTurn,
    QuestionObject,
)

_CATEGORY_ORDER = [
    "fundamentals",
    "project_deep_dive",
    "role_specific_stack",
    "debugging_scenario",
]


class InterviewOrchestrationEngine:
    def decide_next(self, request: OrchestrationStateRequest) -> OrchestrationDecision:
        asked_count = len(request.asked_turns)
        idk_streak = max(request.idk_streak, self._infer_idk_streak(request.asked_turns))

        stop_reason = self._evaluate_stop_conditions(request, asked_count=asked_count, idk_streak=idk_streak)
        if stop_reason:
            return OrchestrationDecision(
                action="end_session",
                reason=f"Stop condition reached: {stop_reason}",
                stop_reason=stop_reason,
            )

        last_turn = request.asked_turns[-1] if request.asked_turns else None

        # If candidate looks stuck, provide a hint before changing topics.
        if last_turn and self._should_offer_hint(last_turn, idk_streak=idk_streak):
            return OrchestrationDecision(
                action="offer_hint",
                reason="Candidate appears stuck or response quality is too low.",
                hint_prompt=self._build_hint_prompt(last_turn),
            )

        # Prefer targeted follow-up when the last answer was short, off-topic, or weak.
        if last_turn:
            follow_up = self._build_follow_up_prompt(last_turn)
            if follow_up:
                return OrchestrationDecision(
                    action="ask_follow_up",
                    reason="Adaptive follow-up triggered by previous answer quality signal.",
                    follow_up_prompt=follow_up,
                )

        scored = self._score_question_pool(request)
        if not scored:
            return OrchestrationDecision(
                action="end_session",
                reason="No eligible questions remaining in pool.",
                stop_reason="question_budget_reached",
            )

        top = scored[0]
        selected = self._find_question(request.question_pool, top.question_id)

        return OrchestrationDecision(
            action="ask_new_question",
            reason="Selected highest composite score based on quality, coverage, time, weakness, and difficulty curve.",
            selected_question=selected,
            policy_scores=scored[:6],
        )

    def summarize_session(self, request: OrchestrationStateRequest) -> OrchestrationSummary:
        turns = request.asked_turns
        if not turns:
            return OrchestrationSummary(
                total_questions_attempted=0,
                answered_questions=0,
                skipped_questions=0,
                coverage_by_category={key: 0 for key in _CATEGORY_ORDER},
                average_score=0.0,
                weak_topics=[],
                strong_topics=[],
                recommendations=["Run a full mock session to generate actionable feedback."],
                time_overrun=False,
            )

        coverage = {key: 0 for key in _CATEGORY_ORDER}
        topic_scores: dict[str, list[float]] = defaultdict(list)

        answered = 0
        skipped = 0
        total_score = 0.0
        total_answer_seconds = 0

        for turn in turns:
            coverage[turn.category] = coverage.get(turn.category, 0) + 1
            topic_scores[turn.focus_topic].append(turn.answer_score)
            total_score += turn.answer_score
            total_answer_seconds += turn.answered_seconds
            if turn.skipped:
                skipped += 1
            else:
                answered += 1

        average = round(total_score / max(1, len(turns)), 3)

        weak_topics: list[str] = []
        strong_topics: list[str] = []
        for topic, scores in topic_scores.items():
            topic_avg = sum(scores) / max(1, len(scores))
            if topic_avg < 0.55:
                weak_topics.append(topic)
            elif topic_avg >= 0.75:
                strong_topics.append(topic)

        time_overrun = total_answer_seconds > (request.total_time_minutes * 60)
        recommendations = self._build_summary_recommendations(
            weak_topics=weak_topics,
            skipped_ratio=(skipped / max(1, len(turns))),
            off_topic_ratio=(sum(1 for item in turns if item.off_topic) / max(1, len(turns))),
            time_overrun=time_overrun,
        )

        return OrchestrationSummary(
            total_questions_attempted=len(turns),
            answered_questions=answered,
            skipped_questions=skipped,
            coverage_by_category=coverage,
            average_score=average,
            weak_topics=sorted(weak_topics),
            strong_topics=sorted(strong_topics),
            recommendations=recommendations,
            time_overrun=time_overrun,
        )

    def framework_metadata(self) -> OrchestrationFrameworkMetadata:
        return OrchestrationFrameworkMetadata(
            decision_policy=(
                "Scoring policy with state-machine guards: evaluate stop conditions first, then hint/follow-up triggers, "
                "then rank remaining questions by composite score (coverage, difficulty curve, quality, time fit, weakness targeting)."
            ),
            pseudocode=(
                "if stop_condition: end_session\n"
                "elif stuck_or_short_answer: offer_hint\n"
                "elif off_topic_or_low_score: ask_follow_up\n"
                "else: score_candidates(); pick argmax(score); ask_new_question"
            ),
            stop_conditions=[
                "asked_questions >= max_questions",
                "remaining_time_minutes <= 0",
                "idk_streak >= 3",
                "all categories covered and remaining_time_minutes < 4",
            ],
            follow_up_policy=[
                "If answer is off-topic, ask a narrow redirect follow-up tied to the original question.",
                "If answer score < 0.45, ask one targeted follow-up on missed tradeoff or missing evidence.",
                "If answer is very short (< 12 words), ask a structured follow-up requesting assumptions, approach, and validation.",
            ],
            hint_policy=[
                "Offer hint when answer is very short, skipped, or idk streak is active.",
                "Hints must provide structure, not solution details.",
                "Allow at most one hint per question before moving on.",
            ],
            summarization_logic=[
                "Aggregate coverage by category.",
                "Compute average score and topic-level weak/strong areas.",
                "Add recommendations from weak topics, skip ratio, off-topic ratio, and time overrun.",
            ],
            edge_case_rules=[
                "Very short answer: trigger hint first, then focused follow-up.",
                "Off-topic answer: force redirect follow-up before new topic.",
                "Repeated I don't know (>=3): end early with coaching summary.",
                "Time overrun risk: prioritize short expected-time questions or terminate with summary.",
            ],
        )

    def _evaluate_stop_conditions(
        self,
        request: OrchestrationStateRequest,
        *,
        asked_count: int,
        idk_streak: int,
    ) -> OrchestrationStopReason | None:
        if asked_count >= request.max_questions:
            return "question_budget_reached"

        if request.remaining_time_minutes <= 0:
            return "time_budget_exhausted"

        if idk_streak >= 3:
            return "repeated_idk"

        covered = {turn.category for turn in request.asked_turns}
        if all(category in covered for category in _CATEGORY_ORDER) and request.remaining_time_minutes < 4:
            return "minimum_coverage_met"

        return None

    def _infer_idk_streak(self, turns: list[OrchestrationTurn]) -> int:
        streak = 0
        for turn in reversed(turns):
            text = (turn.answer_text or "").strip().lower()
            if turn.skipped or text in {"i don't know", "idk", "dont know", "not sure"}:
                streak += 1
                continue
            break
        return streak

    def _should_offer_hint(self, turn: OrchestrationTurn, *, idk_streak: int) -> bool:
        if turn.off_topic:
            return False

        words = len((turn.answer_text or "").split())
        very_short = words < 12 and not turn.off_topic
        low_quality = turn.answer_score < 0.35
        if turn.used_hint:
            return False
        return bool(very_short or turn.skipped or low_quality or idk_streak >= 1)

    def _build_hint_prompt(self, turn: OrchestrationTurn) -> str:
        return (
            "Hint structure: 1) state your assumption, 2) propose a concrete approach, "
            "3) mention one tradeoff and one validation metric. Keep it to 4-6 sentences."
        )

    def _build_follow_up_prompt(self, turn: OrchestrationTurn) -> str | None:
        text = (turn.answer_text or "").strip()
        word_count = len(text.split())

        if turn.off_topic:
            return "Your last answer drifted off-topic. Focus only on the asked scenario and give a direct technical response."

        if word_count < 12:
            return "Give a 3-step answer: assumptions, implementation approach, and how you would validate correctness."

        if turn.answer_score < 0.45:
            return "Add one concrete tradeoff and one failure-mode mitigation for your chosen approach."

        return None

    def _score_question_pool(self, request: OrchestrationStateRequest) -> list[OrchestrationPolicyScore]:
        asked_ids = {turn.question_id for turn in request.asked_turns}
        category_counts = Counter(turn.category for turn in request.asked_turns)

        asked_count = len(request.asked_turns)
        elapsed = max(0, request.total_time_minutes - request.remaining_time_minutes)
        progress = min(1.0, max(asked_count / max(1, request.max_questions), elapsed / max(1, request.total_time_minutes)))

        target_difficulty = self._target_difficulty(request.experience_level, progress)

        weakness_tokens = {item.lower() for item in request.previous_session_weaknesses}
        focus_tokens = {item.lower() for item in request.focus_topics}

        scored: list[OrchestrationPolicyScore] = []
        for question in request.question_pool:
            if question.question_id in asked_ids:
                continue

            quality_component = max(0.0, min(1.0, float(question.quality_score)))

            min_count = min(category_counts.values()) if category_counts else 0
            category_count = category_counts.get(question.category, 0)
            coverage_component = 1.0 if category_count <= min_count else max(0.35, 1.0 - (category_count - min_count) * 0.2)

            difficulty_component = max(0.0, 1.0 - (abs(question.difficulty - target_difficulty) / 4.0))

            if question.expected_time_minutes <= request.remaining_time_minutes:
                time_component = 1.0
            else:
                overflow = question.expected_time_minutes - request.remaining_time_minutes
                time_component = max(0.05, 1.0 - (overflow / max(1, question.expected_time_minutes)))

            focus_text = f"{question.focus_topic} {question.category}".lower()
            weakness_component = 0.45
            if any(token in focus_text for token in weakness_tokens):
                weakness_component += 0.35
            if any(token in focus_text for token in focus_tokens):
                weakness_component += 0.20
            weakness_component = min(1.0, weakness_component)

            composite = (
                (0.28 * coverage_component)
                + (0.24 * difficulty_component)
                + (0.20 * quality_component)
                + (0.16 * time_component)
                + (0.12 * weakness_component)
            )

            scored.append(
                OrchestrationPolicyScore(
                    question_id=question.question_id,
                    category=question.category,
                    topic=question.focus_topic,
                    composite_score=round(composite, 4),
                    quality_component=round(quality_component, 4),
                    coverage_component=round(coverage_component, 4),
                    difficulty_component=round(difficulty_component, 4),
                    time_component=round(time_component, 4),
                    weakness_component=round(weakness_component, 4),
                )
            )

        scored.sort(key=lambda item: item.composite_score, reverse=True)
        return scored

    def _target_difficulty(self, level: str, progress: float) -> float:
        curves: dict[str, tuple[float, float]] = {
            "junior": (2.0, 3.0),
            "mid": (2.6, 3.9),
            "senior": (3.2, 4.6),
            "staff": (3.8, 5.0),
        }
        start, end = curves.get(level, (2.6, 3.9))
        return start + (end - start) * progress

    def _find_question(self, pool: list[QuestionObject], question_id: str) -> QuestionObject | None:
        for item in pool:
            if item.question_id == question_id:
                return item
        return None

    def _build_summary_recommendations(
        self,
        *,
        weak_topics: list[str],
        skipped_ratio: float,
        off_topic_ratio: float,
        time_overrun: bool,
    ) -> list[str]:
        recommendations: list[str] = []

        if weak_topics:
            recommendations.append(
                "Focus next practice on weak topics: " + ", ".join(sorted(set(weak_topics[:4]))) + "."
            )

        if skipped_ratio >= 0.3:
            recommendations.append("Use a baseline answer template to reduce skips: assumptions, approach, tradeoff, validation.")

        if off_topic_ratio >= 0.25:
            recommendations.append("Pause 10 seconds before answering and restate the question scope to stay on-topic.")

        if time_overrun:
            recommendations.append("Practice concise 90-second answers before adding deeper detail to control time usage.")

        if not recommendations:
            recommendations.append("Maintain performance by increasing difficulty by one level in the next session.")

        return recommendations[:5]


orchestration_engine = InterviewOrchestrationEngine()
