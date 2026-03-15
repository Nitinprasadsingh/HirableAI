# AI Interview Trainer PostgreSQL Schema Design

## 1) ERD in Text

users (1) -> (1) candidate_profiles
users (1) -> (N) resumes
users (1) -> (N) interview_sessions
users (1) -> (N) recommendations
users (1) -> (N) progress_snapshots
users (1) -> (N) audit_logs

candidate_profiles (1) -> (N) resumes
candidate_profiles (1) -> (N) skills
candidate_profiles (1) -> (N) projects
candidate_profiles (1) -> (N) experiences
candidate_profiles (1) -> (N) interview_sessions
candidate_profiles (1) -> (N) recommendations
candidate_profiles (1) -> (N) progress_snapshots

skill_categories (1) -> (N) skill_taxonomy
skill_taxonomy (1) -> (N) skill_aliases
skill_taxonomy (1) -> (N) skills
skill_taxonomy (1) -> (N) questions (targeted_skill_id)
skill_taxonomy (1) -> (N) recommendations
skill_taxonomy (1) -> (N) progress_snapshot_skills

resumes (1) -> (N) skills
resumes (1) -> (N) projects
resumes (1) -> (N) experiences
resumes (1) -> (N) interview_sessions

interview_sessions (1) -> (N) questions
interview_sessions (1) -> (N) responses
interview_sessions (1) -> (N) evaluations
interview_sessions (1) -> (N) recommendations
interview_sessions (1) -> (N) progress_snapshots

questions (1) -> (N) responses
responses (1) -> (N) evaluations

evaluations (1) -> (N) recommendations

progress_snapshots (1) -> (N) progress_snapshot_skills

## 2) SQL DDL

Complete DDL, constraints, indexes, pgvector columns, seed data, and report queries are in:
- database/postgres_schema.sql

## 3) Suggested Enums

- user_role: candidate, interviewer, admin, system
- resume_status: uploaded, parsing, parsed, needs_review, confirmed, failed, archived
- session_status: queued, in_progress, completed, abandoned, failed
- question_type: technical, system_design, behavioral, debugging, follow_up
- question_source: llm, template, human
- response_source: text, audio_transcript, imported
- evaluator_type: llm, human, hybrid, rule_engine
- evaluation_verdict: strong, acceptable, needs_improvement, insufficient
- recommendation_type: study_plan, project_practice, mock_interview, resume_improvement, role_gap
- recommendation_status: open, in_progress, completed, dismissed
- audit_action: create, update, delete, login, logout, upload_resume, parse_start, parse_complete, interview_start, interview_submit, evaluation_complete
- pii_retention_class: standard, sensitive, restricted

## 4) Seed Data

Seed data is included in database/postgres_schema.sql for:
- users
- candidate_profiles
- resumes
- skill taxonomy and aliases
- candidate skills
- projects and experiences
- interview_sessions, questions, responses, evaluations
- recommendations
- progress_snapshots and progress_snapshot_skills
- audit_logs

## 5) Query Examples

Included in database/postgres_schema.sql:
- latest session report
- weak skills trend over time
- role readiness over time

## 6) Data Retention Strategy for PII

Data classes:
- standard: low sensitivity metadata (scores, aggregated metrics)
- sensitive: direct candidate identifiers and resume content
- restricted: legal/compliance audit payloads and high-risk fields

Recommended retention windows:
- resumes.parsed_payload, resume files, response answer_text: 12 months after last activity
- interview raw responses and evaluations: 18 months for model QA and fairness audits
- recommendations and progress_snapshots: 24 months for trend analysis
- audit_logs:
  - standard: 12 months
  - sensitive: 24 months
  - restricted: 36 months (or legal requirement)

Operational controls:
- Soft delete first: set deleted_at in users and resumes, hide from product UI immediately.
- Delayed hard delete: scheduled job physically deletes expired rows and object storage files.
- Pseudonymization: replace email, full_name, and free-text answers with irreversible tokens after retention deadline when aggregate analytics must remain.
- Encrypt sensitive fields at rest and in backups.
- Restrict access by role and log every read of sensitive rows in audit_logs.
- Keep analytics tables free of direct identifiers where possible (candidate_profile_id only, no email).

Suggested jobs:
- daily retention job for each table with WHERE created_at < NOW() - interval policy
- weekly orphan cleanup for storage objects not referenced by resumes
- monthly audit log partition pruning if table growth is high
