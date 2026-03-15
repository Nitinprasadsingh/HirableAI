# Results Dashboard Design (Vanilla HTML/CSS/JS)

Last updated: 2026-03-15

## 1) Dashboard Information Architecture

Primary goal: give candidate and coach a clear answer to three questions:
1. How ready is the candidate now?
2. What are the weakest areas by evidence?
3. What should be studied next?

Screen structure (top to bottom):
1. Controls
- Resume ID input
- Load dashboard button
- status indicator

2. Headline metrics
- readiness score
- readiness band
- latest session score
- category coverage count

3. Session summary panel
- recent sessions with questions, weak-area count, readiness per session

4. Profile snapshot panel
- candidate name, headline, top extracted skills, parser confidence

5. Visual analytics
- skill radar chart
- readiness trend chart across sessions

6. Weak areas and study plan
- weak area severity/frequency list
- prioritized study plan (P1/P2/P3)

7. Question-by-question breakdown
- question text
- topic
- score
- verdict
- missed points

8. Feedback templates and scoring bands
- 10 actionable feedback templates
- beginner/intermediate/ready interpretation bands

9. API contract preview
- compact JSON preview for debugging and integration

## 2) API Response Contract For Dashboard

Endpoint:
- GET /v1/dashboard/{resume_id}?limit=120

Response shape:

```json
{
  "resume_id": "uuid",
  "candidate_name": "string",
  "target_role": "Backend Engineer",
  "readiness_score_100": 73.4,
  "readiness_band": "intermediate",
  "scoring_bands": [
    {
      "label": "beginner",
      "min_score": 0,
      "max_score": 54.9,
      "meaning": "Core concepts are emerging; focus on fundamentals and structured answers."
    },
    {
      "label": "intermediate",
      "min_score": 55,
      "max_score": 77.9,
      "meaning": "Solid baseline; deepen tradeoffs, edge cases, and production details."
    },
    {
      "label": "ready",
      "min_score": 78,
      "max_score": 100,
      "meaning": "Interview-ready performance with consistent reasoning and communication."
    }
  ],
  "session_summary": [
    {
      "session_id": "string",
      "completed_at": "ISO-8601",
      "question_count": 6,
      "avg_score_100": 69.2,
      "readiness_score_100": 64.7,
      "readiness_band": "intermediate",
      "weak_area_count": 2
    }
  ],
  "skill_radar": {
    "labels": ["Python", "FastAPI", "PostgreSQL"],
    "values": [78.2, 72.1, 61.4]
  },
  "question_breakdown": [
    {
      "evaluation_id": "string",
      "session_id": "string",
      "question_id": "Q03",
      "question": "Design ...",
      "topic": "PostgreSQL",
      "score_100": 58.0,
      "verdict": "average",
      "is_weak": true,
      "missed_key_points": ["tradeoff comparison", "rollback strategy"],
      "coaching": "Add one alternative and measurable validation metric.",
      "created_at": "ISO-8601"
    }
  ],
  "weak_areas": [
    {
      "topic": "PostgreSQL",
      "severity": "high",
      "avg_score_100": 57.4,
      "frequency": 3,
      "evidence_points": ["missing query-plan evidence"]
    }
  ],
  "trend": [
    {
      "session_id": "string",
      "completed_at": "ISO-8601",
      "readiness_score_100": 61.1,
      "avg_score_100": 66.4
    }
  ],
  "recommended_study_plan": [
    {
      "priority": "P1",
      "title": "Improve PostgreSQL",
      "action": "Run two optimization drills with EXPLAIN ANALYZE.",
      "rationale": "3 weak signals and average 57.4/100.",
      "estimated_days": 4
    }
  ],
  "feedback_templates": ["..."]
}
```

## 3) Scoring Interpretation Bands

1. beginner: 0-54.9
- Fundamentals not stable yet.
- Focus on clear structure and baseline correctness.

2. intermediate: 55-77.9
- Good baseline, but depth/tradeoff quality is inconsistent.
- Focus on reasoning quality and evidence.

3. ready: 78-100
- Consistent correctness, depth, and communication.
- Focus on advanced scenarios and interview speed.

## 4) UI Component List (Vanilla HTML/CSS/JS)

Equivalent to the requested component list, implemented without Next.js:

1. DashboardPageLayout (dashboard.html main sections)
2. DashboardLoaderForm (resume ID + load action)
3. MetricCard (readiness, latest session, coverage)
4. SessionSummaryPanel
5. ProfileSnapshotPanel
6. SkillRadarChart (Chart.js radar)
7. TrendChart (Chart.js line)
8. WeakAreaList
9. StudyPlanList
10. QuestionBreakdownTable
11. FeedbackTemplateList
12. ScoringBandPanel
13. ApiContractPreviewPanel
14. EmptyState / ErrorStatus pill

## 5) 10 Actionable Feedback Message Templates

1. Open with a one-line architecture summary before details.
2. State one explicit tradeoff and why you accepted it.
3. Add one failure mode and one mitigation in every system answer.
4. Include a metric to prove your solution works in production.
5. Use this structure: assumptions -> approach -> tradeoffs -> validation.
6. Compare at least two alternatives before selecting one.
7. Mention rollout safety: canary, monitoring, and rollback trigger.
8. Replace vague terms with concrete components and data flow.
9. In debugging, rank top hypotheses before deep investigation.
10. End with one improvement you would implement next iteration.
