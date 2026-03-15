# Interview Orchestration Algorithm

Last updated: 2026-03-15

This design selects the next best interview action using a hybrid policy:
- state-machine guards for safety and edge cases
- scoring policy for choosing the next question

Implementation references:
- Engine: resume_parser/orchestration_engine.py
- API next action: POST /v1/interviews/orchestration/next
- API summary: POST /v1/interviews/orchestration/summary
- API framework metadata: GET /v1/interviews/orchestration/framework

## 1) Decision Policy (State Machine + Scoring Policy)

Decision order:
1. Stop-condition check
2. Hint gate
3. Adaptive follow-up gate
4. Scored new-question selection

Action space:
- ask_new_question
- ask_follow_up
- offer_hint
- end_session

### Composite scoring for next question

For each candidate question q:
- quality_component: intrinsic question quality score
- coverage_component: preference for under-covered categories
- difficulty_component: closeness to target difficulty curve
- time_component: fit against remaining time
- weakness_component: relevance to prior weak areas and focus topics

Weighted composite:

score(q) = 0.28*coverage + 0.24*difficulty + 0.20*quality + 0.16*time + 0.12*weakness

Highest score wins.

### Difficulty curve target

Progress p in [0,1] is based on max(question_progress, time_progress).
Target difficulty rises with p and experience level:
- junior: 2.0 -> 3.0
- mid: 2.6 -> 3.9
- senior: 3.2 -> 4.6
- staff: 3.8 -> 5.0

## 2) Pseudocode

```
function next_action(state):
    idk_streak = max(state.idk_streak, infer_idk_streak(state.asked_turns))

    stop_reason = evaluate_stop_conditions(state, idk_streak)
    if stop_reason:
        return END_SESSION(stop_reason)

    last_turn = state.asked_turns[-1] if any else null

    if last_turn and should_offer_hint(last_turn, idk_streak):
        return OFFER_HINT(build_hint(last_turn))

    if last_turn:
        follow_up = build_follow_up(last_turn)
        if follow_up:
            return ASK_FOLLOW_UP(follow_up)

    candidates = filter_unasked(state.question_pool, state.asked_turns)
    if candidates is empty:
        return END_SESSION(question_budget_reached)

    scored = []
    for q in candidates:
        coverage = score_coverage(q, state.asked_turns)
        difficulty = score_difficulty(q, target_difficulty(state))
        time_fit = score_time_fit(q.expected_time_minutes, state.remaining_time_minutes)
        weakness = score_weakness_alignment(q, state.previous_session_weaknesses, state.focus_topics)
        quality = q.quality_score
        composite = 0.28*coverage + 0.24*difficulty + 0.20*quality + 0.16*time_fit + 0.12*weakness
        scored.append((q, composite, components))

    best = argmax(scored by composite)
    return ASK_NEW_QUESTION(best.question, scored_top_k)
```

## 3) Stop Conditions

End session when any is true:
1. asked_questions >= max_questions
2. remaining_time_minutes <= 0
3. repeated I don't know streak >= 3
4. all four categories covered and remaining_time_minutes < 4
5. explicit manual_end signal (if UI sends it)

## 4) Follow-Up Generation Policy

Trigger follow-up when previous answer indicates quality risk:
1. Off-topic answer: force redirect follow-up tied to original prompt.
2. Very short answer (<12 words): ask structured follow-up (assumptions, approach, validation).
3. Low score (<0.45): ask one focused follow-up on missing tradeoff or failure mitigation.

Rules:
- Maximum one follow-up per weak turn before moving on.
- Follow-up must stay in same topic family.
- Follow-up should request measurable criteria when possible.

## 5) Hint Policy (Candidate Stuck)

Offer hint when candidate appears blocked:
- skipped answer
- very short answer
- low quality answer (<0.35)
- idk streak >= 1

Hint design:
- Provide response structure, not final solution.
- Template: assumptions -> implementation -> tradeoff -> validation metric.
- Maximum one hint per question.

## 6) End-of-Session Summarization Logic

Session summary computes:
1. total/answered/skipped counts
2. coverage by category
3. average answer score
4. weak topics (topic avg < 0.55)
5. strong topics (topic avg >= 0.75)
6. recommendations from weak topics + behavioral signals
7. time_overrun flag if total answer time > session budget

Recommendation generator adds targeted actions for:
- high skip ratio
- off-topic ratio
- weak topics
- time overrun

## Edge Cases

### Very short answers
- Detect < 12 words.
- Offer hint first.
- If still short on retry, ask compact follow-up then move on.

### Off-topic answers
- Mark off_topic true.
- Ask redirect follow-up before any new topic.

### Repeated I don't know
- Track idk streak via explicit counter and recent turn text.
- End session at streak >= 3 with coaching-oriented summary.

### Time-overrun handling
- Time component penalizes long questions when remaining time is low.
- Prefer short expected-time questions near session end.
- If remaining time <= 0, end session immediately.

## Example Next-Action Response Shape

```
{
  "action": "ask_new_question",
  "reason": "Selected highest composite score based on quality, coverage, time, weakness, and difficulty curve.",
  "selected_question": { ... },
  "policy_scores": [ ... ]
}
```
