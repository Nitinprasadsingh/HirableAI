# Technical Interview Question Generation Framework

Last updated: 2026-03-15

## Overview

This framework generates adaptive technical interview questions from:
- candidate profile
- target role
- experience level
- focus topics
- previous session weaknesses

The generator enforces balanced categories:
- fundamentals
- project_deep_dive
- role_specific_stack
- debugging_scenario

Implementation:
- Engine: resume_parser/question_engine.py
- API endpoint: POST /v1/interviews/questions
- Framework metadata endpoint: GET /v1/interviews/questions/framework

## 1) Prompt Templates For Question Generation

### System template

You are an expert technical interviewer. Generate practical, role-relevant questions. Avoid trivia and generic textbook prompts. Every question must tie to the candidate profile, target role, focus topics, and previous weaknesses.

### User template

Candidate profile JSON:
{candidate_profile_json}

Target role: {target_role}
Experience level: {experience_level}
Focus topics: {focus_topics}
Previous weaknesses: {previous_weaknesses}
Question count: {question_count}

Generate a balanced set across: fundamentals, project_deep_dive, role_specific_stack, debugging_scenario. For each question include: difficulty(1-5), expected_time_minutes, ideal_answer_checklist, adaptive_follow_ups. Return valid JSON only using the provided question object schema.

### Re-generation template

Previous output quality is below threshold. Improve specificity and remove duplicates.
Low-quality question IDs: {low_quality_ids}
Quality issues: {quality_issues}
Preserve category balance and regenerate only flagged questions.
Return valid JSON only.

## 2) JSON Schema For Question Objects

{
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
    "quality_score"
  ],
  "properties": {
    "question_id": { "type": "string", "pattern": "^Q[0-9]{2}$" },
    "category": {
      "type": "string",
      "enum": ["fundamentals", "project_deep_dive", "role_specific_stack", "debugging_scenario"]
    },
    "prompt": { "type": "string", "minLength": 40 },
    "focus_topic": { "type": "string", "minLength": 2 },
    "difficulty": { "type": "integer", "minimum": 1, "maximum": 5 },
    "expected_time_minutes": { "type": "integer", "minimum": 3, "maximum": 30 },
    "ideal_answer_checklist": {
      "type": "array",
      "minItems": 3,
      "maxItems": 8,
      "items": { "type": "string", "minLength": 5 }
    },
    "adaptive_follow_ups": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["trigger", "follow_up_prompt", "intent"],
        "properties": {
          "trigger": { "type": "string" },
          "follow_up_prompt": { "type": "string" },
          "intent": { "type": "string" }
        }
      }
    },
    "quality_score": { "type": "number", "minimum": 0, "maximum": 1 }
  }
}

## 3) Validation Rules

1. Category balance: include all four categories in every batch.
2. Prompt specificity: no vague textbook phrasing; include constraints and tradeoffs.
3. No near-duplicates: prompt similarity must remain below the configured threshold.
4. Checklist completeness: include architecture, tradeoffs, and validation/testing.
5. Difficulty-time alignment: harder questions should allow more time.
6. Low quality threshold: any question below minimum quality is flagged for regeneration.

Engine checks this in code before final response.

## 4) Example Output (10 Questions)

[
  {
    "question_id": "Q01",
    "category": "fundamentals",
    "focus_topic": "FastAPI",
    "difficulty": 3,
    "expected_time_minutes": 11,
    "prompt": "For a Backend Engineer role, explain how request validation, dependency injection, and error handling should be structured in FastAPI for maintainability and low latency.",
    "ideal_answer_checklist": [
      "Explains validation boundaries at API edge",
      "Shows dependency injection usage for services",
      "Covers exception mapping and consistent error shapes",
      "Discusses performance tradeoffs for middleware and validation",
      "Includes testing strategy for routes and dependencies"
    ],
    "adaptive_follow_ups": [
      {
        "trigger": "Answer skips failure handling",
        "follow_up_prompt": "How would you standardize error responses and trace IDs across all endpoints?",
        "intent": "Assess production API reliability"
      }
    ],
    "quality_score": 0.86
  },
  {
    "question_id": "Q02",
    "category": "project_deep_dive",
    "focus_topic": "Resume Parsing Pipeline",
    "difficulty": 4,
    "expected_time_minutes": 16,
    "prompt": "Choose your resume parsing project and explain one architecture decision that improved extraction quality. Include alternatives considered, tradeoffs, and measurable impact.",
    "ideal_answer_checklist": [
      "Defines baseline problem and constraints",
      "Compares at least two design alternatives",
      "Quantifies impact with metrics",
      "Explains edge cases and rollback plan",
      "Mentions what would change in next iteration"
    ],
    "adaptive_follow_ups": [
      {
        "trigger": "Answer has no metrics",
        "follow_up_prompt": "Which two metrics prove your decision improved parser quality in production?",
        "intent": "Force outcome-oriented reasoning"
      }
    ],
    "quality_score": 0.88
  },
  {
    "question_id": "Q03",
    "category": "role_specific_stack",
    "focus_topic": "PostgreSQL",
    "difficulty": 4,
    "expected_time_minutes": 14,
    "prompt": "Design schema and indexing strategy for storing interview sessions, question responses, and trend analytics in PostgreSQL while keeping query latency predictable.",
    "ideal_answer_checklist": [
      "Defines table boundaries and keys",
      "Uses appropriate indexes for main access patterns",
      "Covers write-read tradeoffs",
      "Explains migration strategy",
      "Includes query plan validation approach"
    ],
    "adaptive_follow_ups": [
      {
        "trigger": "Indexing discussion is shallow",
        "follow_up_prompt": "Show one concrete query and explain which index supports it and why.",
        "intent": "Test practical database depth"
      }
    ],
    "quality_score": 0.9
  },
  {
    "question_id": "Q04",
    "category": "debugging_scenario",
    "focus_topic": "Redis + Celery",
    "difficulty": 5,
    "expected_time_minutes": 19,
    "prompt": "A parse-job queue has sudden backlog growth and delayed completions. Walk through how you would debug Redis + Celery behavior, isolate root cause, and prevent recurrence.",
    "ideal_answer_checklist": [
      "Ranks hypotheses before actions",
      "Checks queue depth, worker concurrency, and retry loops",
      "Uses logs and metrics to confirm root cause",
      "Defines immediate mitigation and long-term fix",
      "Adds alerting and capacity guardrails"
    ],
    "adaptive_follow_ups": [
      {
        "trigger": "No incident timeline",
        "follow_up_prompt": "Give a minute-by-minute incident triage sequence for the first 20 minutes.",
        "intent": "Assess on-call decision quality"
      }
    ],
    "quality_score": 0.92
  },
  {
    "question_id": "Q05",
    "category": "fundamentals",
    "focus_topic": "System Design",
    "difficulty": 3,
    "expected_time_minutes": 12,
    "prompt": "Explain idempotency in distributed API design and show how you would apply it to resume parse start requests.",
    "ideal_answer_checklist": [
      "Defines idempotency correctly",
      "Uses request keys and durable state",
      "Handles retries and race conditions",
      "Discusses storage and expiry tradeoffs",
      "Covers test cases for duplicate requests"
    ],
    "adaptive_follow_ups": [
      {
        "trigger": "No race-condition coverage",
        "follow_up_prompt": "How do you prevent two workers from processing the same logical request concurrently?",
        "intent": "Probe concurrency understanding"
      }
    ],
    "quality_score": 0.87
  },
  {
    "question_id": "Q06",
    "category": "project_deep_dive",
    "focus_topic": "LLM Evaluation",
    "difficulty": 4,
    "expected_time_minutes": 15,
    "prompt": "From your interview trainer project, explain how you would design answer evaluation to combine rubric consistency with LLM flexibility.",
    "ideal_answer_checklist": [
      "Defines deterministic rubric dimensions",
      "Explains LLM prompt and output controls",
      "Adds calibration and drift checks",
      "Covers fairness and bias mitigation",
      "Includes human-review fallback path"
    ],
    "adaptive_follow_ups": [
      {
        "trigger": "No quality assurance plan",
        "follow_up_prompt": "Which offline and online checks will detect evaluator regressions?",
        "intent": "Validate reliability mindset"
      }
    ],
    "quality_score": 0.89
  },
  {
    "question_id": "Q07",
    "category": "role_specific_stack",
    "focus_topic": "FastAPI + PostgreSQL",
    "difficulty": 4,
    "expected_time_minutes": 14,
    "prompt": "Design an endpoint and service flow for generating adaptive interview questions from profile data, including caching and database consistency concerns.",
    "ideal_answer_checklist": [
      "Defines endpoint contract and validation",
      "Separates service orchestration from persistence",
      "Explains caching policy and invalidation",
      "Handles partial failures and retries",
      "Includes observability metrics"
    ],
    "adaptive_follow_ups": [
      {
        "trigger": "No consistency strategy",
        "follow_up_prompt": "How do you avoid stale profile context when generating questions?",
        "intent": "Assess state-consistency reasoning"
      }
    ],
    "quality_score": 0.88
  },
  {
    "question_id": "Q08",
    "category": "debugging_scenario",
    "focus_topic": "Slow Query Investigation",
    "difficulty": 5,
    "expected_time_minutes": 18,
    "prompt": "Dashboard readiness trend query becomes slow after data growth. Describe how you would isolate bottlenecks, validate index strategy, and safely ship performance fixes.",
    "ideal_answer_checklist": [
      "Collects baseline with EXPLAIN ANALYZE",
      "Identifies cardinality and join bottlenecks",
      "Proposes index or query rewrite with reasoning",
      "Defines rollback and verification plan",
      "Tracks latency regression after deployment"
    ],
    "adaptive_follow_ups": [
      {
        "trigger": "No safe rollout strategy",
        "follow_up_prompt": "How will you deploy query changes without impacting live traffic?",
        "intent": "Check operational safety"
      }
    ],
    "quality_score": 0.91
  },
  {
    "question_id": "Q09",
    "category": "fundamentals",
    "focus_topic": "API Security",
    "difficulty": 3,
    "expected_time_minutes": 11,
    "prompt": "For a backend interview trainer API, explain authentication, authorization, and input-hardening controls needed for resume uploads and interview responses.",
    "ideal_answer_checklist": [
      "Separates authentication from authorization",
      "Describes role-based access checks",
      "Covers file and payload validation",
      "Includes abuse protection and rate limits",
      "Mentions audit logging for sensitive actions"
    ],
    "adaptive_follow_ups": [
      {
        "trigger": "No threat model assumptions",
        "follow_up_prompt": "Which top two abuse scenarios are most likely and how do your controls stop them?",
        "intent": "Assess security prioritization"
      }
    ],
    "quality_score": 0.86
  },
  {
    "question_id": "Q10",
    "category": "project_deep_dive",
    "focus_topic": "Adaptive Follow-Up Logic",
    "difficulty": 4,
    "expected_time_minutes": 15,
    "prompt": "Describe how you would design adaptive follow-up question logic that responds to weak areas without making the interview flow repetitive.",
    "ideal_answer_checklist": [
      "Defines weakness detection signals",
      "Explains follow-up selection policy",
      "Prevents duplicate or looping prompts",
      "Balances depth with interview time budget",
      "Evaluates impact on candidate outcomes"
    ],
    "adaptive_follow_ups": [
      {
        "trigger": "No anti-repetition mechanism",
        "follow_up_prompt": "How will you enforce diversity constraints across follow-up prompts in one session?",
        "intent": "Evaluate adaptive system design depth"
      }
    ],
    "quality_score": 0.9
  }
]

## 5) Re-generation Strategy If Quality Score Is Low

Regenerate if any condition is true:
- overall_quality_score < 0.78
- any question quality_score < 0.62
- any duplicate or near-duplicate prompt is detected
- category coverage is incomplete

Steps:
1. Identify flagged question_ids and preserve high-quality questions.
2. Regenerate only flagged questions using weaknesses and project context.
3. Increase prompt specificity by forcing constraints, metrics, and tradeoff language.
4. Re-run validation and quality scoring.
5. Stop after 2 regeneration rounds and return warnings if still below threshold.

## API Example Request

POST /v1/interviews/questions

{
  "target_role": "Backend Engineer",
  "experience_level": "mid",
  "focus_topics": ["FastAPI", "PostgreSQL", "Redis"],
  "previous_session_weaknesses": ["System Design", "Query Optimization"],
  "question_count": 10,
  "candidate_profile": {
    "skills": [{"canonical": "Python"}, {"canonical": "FastAPI"}],
    "projects": [{"name": "Resume Intelligence API"}]
  }
}
