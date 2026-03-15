# LLM Answer Evaluation Framework

Last updated: 2026-03-15

This framework evaluates interview answers with strict rubric scoring and low-hallucination safeguards.

Implementation references:
- Engine: resume_parser/evaluation_engine.py
- API: POST /v1/interviews/evaluate
- Metadata: GET /v1/interviews/evaluate/framework

## 1) Rubric Table (0-5)

| Criterion | Weight | 0 | 1 | 2 | 3 | 4 | 5 |
|---|---:|---|---|---|---|---|---|
| correctness | 0.32 | Incorrect/unrelated | Mostly incorrect | Partially correct | Mostly correct | Correct and sound | Fully correct and precise |
| depth | 0.23 | Superficial | Very shallow | Some detail | Reasonable depth | Deep practical detail | Excellent production depth |
| reasoning_tradeoffs | 0.20 | No reasoning | Weak rationale | Basic rationale | Clear rationale + 1 tradeoff | Multiple tradeoffs | Strong comparative reasoning + mitigations |
| clarity_communication | 0.15 | Incoherent | Hard to follow | Partially clear | Clear with structure | Well structured | Highly clear and concise |
| confidence_signal | 0.10 | Very uncertain | Highly tentative | Mixed confidence | Moderately confident | Confident and grounded | Highly confident and justified |

## 2) Evaluation Prompt

### System prompt

You are a strict technical interview evaluator. Score using rubric only. Do not invent facts that are not in candidate answer. Return only valid JSON with no markdown, no extra keys, and no prose outside JSON.

### User prompt template

Question: {question}
Target role: {target_role}
Experience level: {experience_level}
Focus topic: {focus_topic}
Difficulty: {difficulty}
Ideal answer checklist: {ideal_answer_checklist_json}
Candidate answer: {candidate_answer}

Evaluate criteria: correctness, depth, reasoning/trade-offs, clarity/communication, confidence (infer only if answer indicates it).
Rules:
- Use strict rubric scoring 0-5.
- Evidence snippets must be exact quotes from candidate answer.
- Include missed key points from checklist.
- Add short better-answer coaching.
- Return only valid JSON matching schema.

## 3) JSON Schema For Evaluator Output

{
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
    "formula_version"
  ],
  "properties": {
    "question": { "type": "string" },
    "target_role": { "type": "string" },
    "experience_level": { "type": "string", "enum": ["junior", "mid", "senior", "staff"] },
    "focus_topic": { "type": ["string", "null"] },
    "difficulty": { "type": "integer", "minimum": 1, "maximum": 5 },
    "correctness": { "$ref": "#/$defs/criterionScore" },
    "depth": { "$ref": "#/$defs/criterionScore" },
    "reasoning_tradeoffs": { "$ref": "#/$defs/criterionScore" },
    "clarity_communication": { "$ref": "#/$defs/criterionScore" },
    "confidence_signal": { "$ref": "#/$defs/criterionScore" },
    "weighted_final_score_100": { "type": "number", "minimum": 0, "maximum": 100 },
    "weighted_final_score_10": { "type": "number", "minimum": 0, "maximum": 10 },
    "verdict": { "type": "string", "enum": ["weak", "average", "strong"] },
    "confidence_in_score": { "type": "number", "minimum": 0, "maximum": 1 },
    "evidence_snippets": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["criterion", "quote", "reason"],
        "properties": {
          "criterion": { "type": "string" },
          "quote": { "type": "string" },
          "reason": { "type": "string" }
        }
      }
    },
    "missed_key_points": { "type": "array", "items": { "type": "string" } },
    "better_answer_coaching": { "type": "string", "maxLength": 280 },
    "formula_version": { "type": "string" },
    "warnings": { "type": "array", "items": { "type": "string" } }
  },
  "$defs": {
    "criterionScore": {
      "type": "object",
      "required": ["value", "rationale"],
      "properties": {
        "value": { "type": "integer", "minimum": 0, "maximum": 5 },
        "rationale": { "type": "string" }
      }
    }
  }
}

## 4) Post-Processing Formula (Weighted Final Score)

Given criterion scores on 0-5 scale:
- correctness: c
- depth: d
- reasoning_tradeoffs: r
- clarity_communication: l
- confidence_signal: f

Weights:
- wc = 0.32
- wd = 0.23
- wr = 0.20
- wl = 0.15
- wf = 0.10

Formula:

final_score_5 = c*wc + d*wd + r*wr + l*wl + f*wf
weighted_final_score_100 = round((final_score_5 / 5) * 100, 1)
weighted_final_score_10 = round(weighted_final_score_100 / 10, 2)

Verdict mapping:
- weak: score < 55
- average: 55 <= score < 78
- strong: score >= 78

## 5) Calibration Strategy To Reduce Scoring Drift

1. Anchor set calibration
- Maintain fixed benchmark answers per role and level with gold criterion labels.
- Re-score weekly and compare criterion deltas to anchor labels.

2. Drift thresholds
- Compute mean absolute deviation by criterion.
- Trigger review if deviation exceeds 0.6 points on 0-5 scale.

3. Dual scoring audit
- Double-score 10% random samples using a second prompt/version.
- Use adjudication notes to refine rubric instructions.

4. Version discipline
- Version prompt templates and scoring formula.
- Do not mix metrics across versions without explicit normalization.

5. Confidence gating
- If confidence_in_score < 0.45, route answer to secondary pass or human review.

6. Hallucination controls
- Reject evidence snippets that are not exact substrings of candidate answer.
- Cap confidence if evidence coverage is too low.

## 6) Worked Examples (Weak / Average / Strong)

### Example A: Weak

Input question:
How would you scale async parse jobs?

Candidate answer:
I would maybe add more servers and maybe cache everything. It should work.

Evaluation summary:
- correctness: 1
- depth: 1
- reasoning_tradeoffs: 0
- clarity_communication: 2
- confidence_signal: 0
- weighted_final_score_100: 22.6
- missed_key_points: retry strategy, dead-letter handling, queue lag metrics, failure isolation
- coaching: add concrete queue architecture, retry policy, and measurable SLOs

### Example B: Average

Input question:
How would you scale async parse jobs?

Candidate answer:
I would use Redis and Celery workers with retries. I would monitor queue length and error rate. If workers fail often, I would increase concurrency and investigate heavy job types.

Evaluation summary:
- correctness: 3
- depth: 3
- reasoning_tradeoffs: 3
- clarity_communication: 4
- confidence_signal: 3
- weighted_final_score_100: 63.6
- missed_key_points: dead-letter queue design, backpressure policy, rollout validation
- coaching: add tradeoff comparison and explicit mitigation for retry storms

### Example C: Strong

Input question:
How would you scale async parse jobs?

Candidate answer:
I would split fast and heavy workloads into separate queues, set bounded retries with jittered backoff, and push poison messages to dead-letter queues. I would autoscale workers from queue lag and throughput, then validate changes with error budget and completion latency trends.

Evaluation summary:
- correctness: 5
- depth: 4
- reasoning_tradeoffs: 5
- clarity_communication: 4
- confidence_signal: 4
- weighted_final_score_100: 89.4
- missed_key_points: none critical
- coaching: include one rollback trigger and one capacity ceiling threshold
