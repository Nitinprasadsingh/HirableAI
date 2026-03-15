BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS vector;

-- =========================
-- Enums
-- =========================
CREATE TYPE user_role AS ENUM ('candidate', 'interviewer', 'admin', 'system');
CREATE TYPE resume_status AS ENUM ('uploaded', 'parsing', 'parsed', 'needs_review', 'confirmed', 'failed', 'archived');
CREATE TYPE session_status AS ENUM ('queued', 'in_progress', 'completed', 'abandoned', 'failed');
CREATE TYPE question_type AS ENUM ('technical', 'system_design', 'behavioral', 'debugging', 'follow_up');
CREATE TYPE question_source AS ENUM ('llm', 'template', 'human');
CREATE TYPE response_source AS ENUM ('text', 'audio_transcript', 'imported');
CREATE TYPE evaluator_type AS ENUM ('llm', 'human', 'hybrid', 'rule_engine');
CREATE TYPE evaluation_verdict AS ENUM ('strong', 'acceptable', 'needs_improvement', 'insufficient');
CREATE TYPE recommendation_type AS ENUM ('study_plan', 'project_practice', 'mock_interview', 'resume_improvement', 'role_gap');
CREATE TYPE recommendation_status AS ENUM ('open', 'in_progress', 'completed', 'dismissed');
CREATE TYPE audit_action AS ENUM (
  'create', 'update', 'delete',
  'login', 'logout',
  'upload_resume', 'parse_start', 'parse_complete',
  'interview_start', 'interview_submit', 'evaluation_complete'
);
CREATE TYPE pii_retention_class AS ENUM ('standard', 'sensitive', 'restricted');

-- =========================
-- Utility trigger
-- =========================
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =========================
-- Core user and profile tables
-- =========================
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email CITEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  full_name TEXT,
  role user_role NOT NULL DEFAULT 'candidate',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  last_login_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at TIMESTAMPTZ,
  CONSTRAINT chk_users_email CHECK (POSITION('@' IN email) > 1)
);

CREATE TABLE candidate_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  target_role TEXT,
  years_experience NUMERIC(4,1) CHECK (years_experience >= 0),
  location TEXT,
  summary TEXT,
  primary_skills JSONB NOT NULL DEFAULT '[]'::jsonb,
  profile_embedding VECTOR(1536),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE resumes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  candidate_profile_id UUID REFERENCES candidate_profiles(id) ON DELETE SET NULL,
  original_filename TEXT NOT NULL,
  storage_uri TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  file_size_bytes BIGINT NOT NULL CHECK (file_size_bytes > 0),
  sha256 CHAR(64) NOT NULL UNIQUE,
  status resume_status NOT NULL DEFAULT 'uploaded',
  consent_version TEXT NOT NULL,
  parse_version INTEGER NOT NULL DEFAULT 1 CHECK (parse_version > 0),
  parsed_payload JSONB,
  resume_embedding VECTOR(1536),
  uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  parsed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at TIMESTAMPTZ,
  CONSTRAINT chk_resumes_mime_type CHECK (mime_type IN ('application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'))
);

-- =========================
-- Skill taxonomy and extracted skills
-- =========================
CREATE TABLE skill_categories (
  id SMALLSERIAL PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL
);

CREATE TABLE skill_taxonomy (
  id BIGSERIAL PRIMARY KEY,
  canonical_name TEXT NOT NULL UNIQUE,
  category_id SMALLINT REFERENCES skill_categories(id) ON DELETE SET NULL,
  description TEXT,
  embedding VECTOR(384),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE skill_aliases (
  id BIGSERIAL PRIMARY KEY,
  taxonomy_skill_id BIGINT NOT NULL REFERENCES skill_taxonomy(id) ON DELETE CASCADE,
  alias TEXT NOT NULL,
  normalized_alias TEXT NOT NULL,
  confidence_weight NUMERIC(4,3) NOT NULL DEFAULT 1.000 CHECK (confidence_weight > 0 AND confidence_weight <= 1.5),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (taxonomy_skill_id, normalized_alias),
  UNIQUE (normalized_alias)
);

CREATE TABLE skills (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  candidate_profile_id UUID NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
  taxonomy_skill_id BIGINT REFERENCES skill_taxonomy(id) ON DELETE SET NULL,
  source_resume_id UUID REFERENCES resumes(id) ON DELETE SET NULL,
  raw_name TEXT NOT NULL,
  canonical_name TEXT NOT NULL,
  category TEXT,
  proficiency_score NUMERIC(5,2) CHECK (proficiency_score BETWEEN 0 AND 100),
  confidence_score NUMERIC(5,4) NOT NULL CHECK (confidence_score BETWEEN 0 AND 1),
  source_section TEXT,
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  last_seen_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (candidate_profile_id, canonical_name)
);

-- =========================
-- Resume entities
-- =========================
CREATE TABLE projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  candidate_profile_id UUID NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
  resume_id UUID REFERENCES resumes(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  role_title TEXT,
  description TEXT NOT NULL,
  impact TEXT,
  tech_stack JSONB NOT NULL DEFAULT '[]'::jsonb,
  project_url TEXT,
  start_date DATE,
  end_date DATE,
  is_current BOOLEAN NOT NULL DEFAULT FALSE,
  confidence_score NUMERIC(5,4) NOT NULL CHECK (confidence_score BETWEEN 0 AND 1),
  summary_embedding VECTOR(768),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT chk_projects_dates CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date),
  CONSTRAINT chk_projects_current CHECK (NOT (is_current AND end_date IS NOT NULL))
);

CREATE TABLE experiences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  candidate_profile_id UUID NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
  resume_id UUID REFERENCES resumes(id) ON DELETE SET NULL,
  company_name TEXT NOT NULL,
  title TEXT NOT NULL,
  employment_type TEXT,
  location TEXT,
  summary TEXT,
  skills_used JSONB NOT NULL DEFAULT '[]'::jsonb,
  start_date DATE,
  end_date DATE,
  is_current BOOLEAN NOT NULL DEFAULT FALSE,
  confidence_score NUMERIC(5,4) NOT NULL CHECK (confidence_score BETWEEN 0 AND 1),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT chk_experiences_dates CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date),
  CONSTRAINT chk_experiences_current CHECK (NOT (is_current AND end_date IS NOT NULL))
);

-- =========================
-- Interviewing and evaluation
-- =========================
CREATE TABLE interview_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  candidate_profile_id UUID NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
  resume_id UUID REFERENCES resumes(id) ON DELETE SET NULL,
  status session_status NOT NULL DEFAULT 'queued',
  target_role TEXT,
  llm_provider TEXT,
  llm_model TEXT,
  started_at TIMESTAMPTZ,
  ended_at TIMESTAMPTZ,
  overall_score NUMERIC(5,2) CHECK (overall_score BETWEEN 0 AND 100),
  readiness_score NUMERIC(5,2) CHECK (readiness_score BETWEEN 0 AND 100),
  weak_skills JSONB NOT NULL DEFAULT '[]'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT chk_sessions_time CHECK (ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at)
);

CREATE TABLE questions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
  question_order INTEGER NOT NULL CHECK (question_order > 0),
  question_type question_type NOT NULL,
  source question_source NOT NULL DEFAULT 'llm',
  prompt TEXT NOT NULL,
  context JSONB NOT NULL DEFAULT '{}'::jsonb,
  targeted_skill_id BIGINT REFERENCES skill_taxonomy(id) ON DELETE SET NULL,
  project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
  difficulty_level SMALLINT NOT NULL DEFAULT 3 CHECK (difficulty_level BETWEEN 1 AND 5),
  prompt_version TEXT,
  question_embedding VECTOR(1536),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (session_id, question_order),
  UNIQUE (id, session_id)
);

CREATE TABLE responses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
  question_id UUID NOT NULL,
  attempt_no SMALLINT NOT NULL DEFAULT 1 CHECK (attempt_no > 0),
  source response_source NOT NULL DEFAULT 'text',
  answer_text TEXT,
  answer_audio_uri TEXT,
  is_skipped BOOLEAN NOT NULL DEFAULT FALSE,
  duration_seconds INTEGER CHECK (duration_seconds >= 0),
  answered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  answer_embedding VECTOR(1536),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (id, session_id),
  UNIQUE (question_id, attempt_no),
  FOREIGN KEY (question_id, session_id) REFERENCES questions(id, session_id) ON DELETE CASCADE
);

CREATE TABLE evaluations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
  response_id UUID NOT NULL,
  evaluation_version SMALLINT NOT NULL DEFAULT 1 CHECK (evaluation_version > 0),
  evaluator evaluator_type NOT NULL DEFAULT 'llm',
  rubric_version TEXT NOT NULL,
  verdict evaluation_verdict NOT NULL,
  score_overall NUMERIC(5,2) NOT NULL CHECK (score_overall BETWEEN 0 AND 100),
  score_breakdown JSONB NOT NULL DEFAULT '{}'::jsonb,
  strengths JSONB NOT NULL DEFAULT '[]'::jsonb,
  weaknesses JSONB NOT NULL DEFAULT '[]'::jsonb,
  weak_skill_ids BIGINT[] NOT NULL DEFAULT '{}',
  evaluator_model TEXT,
  prompt_tokens INTEGER CHECK (prompt_tokens >= 0),
  completion_tokens INTEGER CHECK (completion_tokens >= 0),
  latency_ms INTEGER CHECK (latency_ms >= 0),
  evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  FOREIGN KEY (response_id, session_id) REFERENCES responses(id, session_id) ON DELETE CASCADE,
  UNIQUE (response_id, evaluation_version)
);

CREATE TABLE recommendations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  candidate_profile_id UUID NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
  session_id UUID REFERENCES interview_sessions(id) ON DELETE SET NULL,
  taxonomy_skill_id BIGINT REFERENCES skill_taxonomy(id) ON DELETE SET NULL,
  evaluation_id UUID REFERENCES evaluations(id) ON DELETE SET NULL,
  recommendation_type recommendation_type NOT NULL,
  status recommendation_status NOT NULL DEFAULT 'open',
  priority SMALLINT NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
  title TEXT NOT NULL,
  recommendation_text TEXT NOT NULL,
  action_items JSONB NOT NULL DEFAULT '[]'::jsonb,
  due_date DATE,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT chk_recommendation_dates CHECK (completed_at IS NULL OR completed_at >= generated_at)
);

CREATE TABLE progress_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  candidate_profile_id UUID NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
  session_id UUID REFERENCES interview_sessions(id) ON DELETE SET NULL,
  snapshot_date DATE NOT NULL,
  target_role TEXT,
  readiness_score NUMERIC(5,2) CHECK (readiness_score BETWEEN 0 AND 100),
  confidence_score NUMERIC(5,2) CHECK (confidence_score BETWEEN 0 AND 100),
  weak_skill_count INTEGER NOT NULL DEFAULT 0 CHECK (weak_skill_count >= 0),
  weak_skills JSONB NOT NULL DEFAULT '[]'::jsonb,
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE progress_snapshot_skills (
  snapshot_id UUID NOT NULL REFERENCES progress_snapshots(id) ON DELETE CASCADE,
  taxonomy_skill_id BIGINT NOT NULL REFERENCES skill_taxonomy(id) ON DELETE CASCADE,
  score NUMERIC(5,2) NOT NULL CHECK (score BETWEEN 0 AND 100),
  delta_from_prev NUMERIC(6,2),
  is_weak BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (snapshot_id, taxonomy_skill_id)
);

CREATE TABLE audit_logs (
  id BIGSERIAL PRIMARY KEY,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  actor_role user_role,
  action audit_action NOT NULL,
  entity_table TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  request_id UUID,
  status_code INTEGER,
  ip_address INET,
  user_agent TEXT,
  pii_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
  old_data JSONB,
  new_data JSONB,
  retention_class pii_retention_class NOT NULL DEFAULT 'standard'
);

-- =========================
-- Updated at triggers
-- =========================
CREATE TRIGGER trg_users_updated_at
BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_candidate_profiles_updated_at
BEFORE UPDATE ON candidate_profiles
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_resumes_updated_at
BEFORE UPDATE ON resumes
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_skill_taxonomy_updated_at
BEFORE UPDATE ON skill_taxonomy
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_skills_updated_at
BEFORE UPDATE ON skills
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_projects_updated_at
BEFORE UPDATE ON projects
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_experiences_updated_at
BEFORE UPDATE ON experiences
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_interview_sessions_updated_at
BEFORE UPDATE ON interview_sessions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_recommendations_updated_at
BEFORE UPDATE ON recommendations
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =========================
-- Performance indexes
-- =========================
CREATE INDEX idx_users_role_active ON users(role, is_active) WHERE deleted_at IS NULL;

CREATE INDEX idx_resumes_user_uploaded ON resumes(user_id, uploaded_at DESC);
CREATE INDEX idx_resumes_status ON resumes(status, updated_at DESC);
CREATE INDEX idx_resumes_profile ON resumes(candidate_profile_id, uploaded_at DESC);
CREATE INDEX idx_resumes_payload_gin ON resumes USING GIN (parsed_payload jsonb_path_ops);
CREATE INDEX idx_resumes_embedding_ivfflat ON resumes USING ivfflat (resume_embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX idx_skill_taxonomy_category ON skill_taxonomy(category_id, canonical_name);
CREATE INDEX idx_skill_taxonomy_embedding_ivfflat ON skill_taxonomy USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_skill_aliases_lookup ON skill_aliases(normalized_alias);

CREATE INDEX idx_skills_profile_confidence ON skills(candidate_profile_id, confidence_score DESC);
CREATE INDEX idx_skills_taxonomy ON skills(taxonomy_skill_id);

CREATE INDEX idx_projects_profile_dates ON projects(candidate_profile_id, start_date DESC);
CREATE INDEX idx_projects_techstack_gin ON projects USING GIN (tech_stack jsonb_path_ops);
CREATE INDEX idx_projects_embedding_ivfflat ON projects USING ivfflat (summary_embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX idx_experiences_profile_dates ON experiences(candidate_profile_id, start_date DESC);
CREATE INDEX idx_experiences_skills_gin ON experiences USING GIN (skills_used jsonb_path_ops);

CREATE INDEX idx_sessions_user_started ON interview_sessions(user_id, started_at DESC);
CREATE INDEX idx_sessions_profile_started ON interview_sessions(candidate_profile_id, started_at DESC);
CREATE INDEX idx_sessions_status ON interview_sessions(status, created_at DESC);
CREATE INDEX idx_sessions_weak_skills_gin ON interview_sessions USING GIN (weak_skills jsonb_path_ops);

CREATE INDEX idx_questions_session_order ON questions(session_id, question_order);
CREATE INDEX idx_questions_targeted_skill ON questions(targeted_skill_id);
CREATE INDEX idx_questions_embedding_ivfflat ON questions USING ivfflat (question_embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX idx_responses_session_answered ON responses(session_id, answered_at DESC);
CREATE INDEX idx_responses_question ON responses(question_id);
CREATE INDEX idx_responses_embedding_ivfflat ON responses USING ivfflat (answer_embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX idx_evaluations_session_time ON evaluations(session_id, evaluated_at DESC);
CREATE INDEX idx_evaluations_score ON evaluations(score_overall);
CREATE INDEX idx_evaluations_weak_skill_ids_gin ON evaluations USING GIN (weak_skill_ids);

CREATE INDEX idx_recommendations_profile_status ON recommendations(candidate_profile_id, status, priority);
CREATE INDEX idx_recommendations_skill ON recommendations(taxonomy_skill_id, status);

CREATE INDEX idx_progress_snapshots_profile_date ON progress_snapshots(candidate_profile_id, snapshot_date DESC);
CREATE INDEX idx_progress_snapshots_user_date ON progress_snapshots(user_id, snapshot_date DESC);
CREATE INDEX idx_progress_snapshots_weak_gin ON progress_snapshots USING GIN (weak_skills jsonb_path_ops);
CREATE UNIQUE INDEX ux_progress_daily_profile_snapshot ON progress_snapshots(candidate_profile_id, snapshot_date) WHERE session_id IS NULL;
CREATE UNIQUE INDEX ux_progress_session_snapshot ON progress_snapshots(session_id) WHERE session_id IS NOT NULL;

CREATE INDEX idx_progress_snapshot_skills_skill ON progress_snapshot_skills(taxonomy_skill_id, is_weak);

CREATE INDEX idx_audit_logs_occurred ON audit_logs(occurred_at DESC);
CREATE INDEX idx_audit_logs_entity ON audit_logs(entity_table, entity_id, occurred_at DESC);
CREATE INDEX idx_audit_logs_actor ON audit_logs(actor_user_id, occurred_at DESC);
CREATE INDEX idx_audit_logs_request ON audit_logs(request_id);

-- =========================
-- Example seed data
-- =========================
INSERT INTO users (id, email, password_hash, full_name, role)
VALUES
  ('11111111-1111-1111-1111-111111111111', 'nitin@example.com', '$2b$12$examplehashfornitin', 'Nitin Candidate', 'candidate'),
  ('22222222-2222-2222-2222-222222222222', 'coach@example.com', '$2b$12$examplehashforcoach', 'Interviewer Coach', 'interviewer');

INSERT INTO candidate_profiles (id, user_id, target_role, years_experience, location, summary, primary_skills)
VALUES
  (
    '33333333-3333-3333-3333-333333333333',
    '11111111-1111-1111-1111-111111111111',
    'Backend Engineer',
    3.5,
    'Bengaluru, IN',
    'Backend-focused engineer with FastAPI, PostgreSQL, and cloud deployment experience.',
    '["Python", "FastAPI", "PostgreSQL", "Redis"]'::jsonb
  );

INSERT INTO resumes (
  id, user_id, candidate_profile_id, original_filename, storage_uri, mime_type, file_size_bytes,
  sha256, status, consent_version, parse_version, parsed_payload, uploaded_at, parsed_at
)
VALUES
  (
    '44444444-4444-4444-4444-444444444444',
    '11111111-1111-1111-1111-111111111111',
    '33333333-3333-3333-3333-333333333333',
    'nitin_resume.docx',
    's3://ai-interview/resumes/44444444-4444-4444-4444-444444444444.docx',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    245760,
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    'confirmed',
    'v1',
    2,
    '{"quality":{"overall_confidence":0.87},"profile":{"candidate_name":"Nitin"}}'::jsonb,
    NOW() - INTERVAL '10 day',
    NOW() - INTERVAL '9 day'
  );

INSERT INTO skill_categories (id, code, display_name)
VALUES
  (1, 'programming_language', 'Programming Languages'),
  (2, 'framework', 'Frameworks'),
  (3, 'database', 'Databases'),
  (4, 'infrastructure', 'Infrastructure');

INSERT INTO skill_taxonomy (id, canonical_name, category_id, description)
VALUES
  (1001, 'Python', 1, 'General purpose programming language'),
  (1002, 'FastAPI', 2, 'Python web framework for APIs'),
  (1003, 'PostgreSQL', 3, 'Relational database'),
  (1004, 'Redis', 4, 'In-memory datastore and queue backend');

INSERT INTO skill_aliases (taxonomy_skill_id, alias, normalized_alias, confidence_weight)
VALUES
  (1001, 'python3', 'python3', 1.000),
  (1002, 'fast api', 'fast api', 0.980),
  (1003, 'postgres', 'postgres', 0.970),
  (1004, 'redis-cache', 'redis-cache', 0.940);

INSERT INTO skills (
  id, candidate_profile_id, taxonomy_skill_id, source_resume_id, raw_name, canonical_name, category,
  proficiency_score, confidence_score, source_section, evidence, last_seen_at
)
VALUES
  (
    '55555555-5555-5555-5555-555555555551',
    '33333333-3333-3333-3333-333333333333',
    1001,
    '44444444-4444-4444-4444-444444444444',
    'Python',
    'Python',
    'programming_language',
    84.00,
    0.9400,
    'skills',
    '{"source":"resume_parser","mentions":8}'::jsonb,
    NOW() - INTERVAL '9 day'
  ),
  (
    '55555555-5555-5555-5555-555555555552',
    '33333333-3333-3333-3333-333333333333',
    1002,
    '44444444-4444-4444-4444-444444444444',
    'FastAPI',
    'FastAPI',
    'framework',
    79.00,
    0.9100,
    'projects',
    '{"source":"resume_parser","mentions":5}'::jsonb,
    NOW() - INTERVAL '9 day'
  ),
  (
    '55555555-5555-5555-5555-555555555553',
    '33333333-3333-3333-3333-333333333333',
    1003,
    '44444444-4444-4444-4444-444444444444',
    'PostgreSQL',
    'PostgreSQL',
    'database',
    72.00,
    0.8800,
    'experience',
    '{"source":"resume_parser","mentions":4}'::jsonb,
    NOW() - INTERVAL '9 day'
  );

INSERT INTO projects (
  id, candidate_profile_id, resume_id, title, role_title, description, impact, tech_stack, project_url,
  start_date, end_date, is_current, confidence_score
)
VALUES
  (
    '66666666-6666-6666-6666-666666666661',
    '33333333-3333-3333-3333-333333333333',
    '44444444-4444-4444-4444-444444444444',
    'Resume Intelligence API',
    'Backend Developer',
    'Built async parsing and confidence scoring pipeline for resume ingestion.',
    'Reduced manual screening time by 35 percent.',
    '["Python","FastAPI","PostgreSQL","Redis"]'::jsonb,
    'https://example.com/projects/resume-intelligence',
    '2024-01-01',
    '2024-09-15',
    FALSE,
    0.8900
  );

INSERT INTO experiences (
  id, candidate_profile_id, resume_id, company_name, title, employment_type, location, summary,
  skills_used, start_date, end_date, is_current, confidence_score
)
VALUES
  (
    '77777777-7777-7777-7777-777777777771',
    '33333333-3333-3333-3333-333333333333',
    '44444444-4444-4444-4444-444444444444',
    'Acme Tech',
    'Software Engineer',
    'full_time',
    'Bengaluru, IN',
    'Developed backend APIs and data pipelines for hiring workflows.',
    '["Python","FastAPI","PostgreSQL"]'::jsonb,
    '2022-06-01',
    NULL,
    TRUE,
    0.9000
  );

INSERT INTO interview_sessions (
  id, user_id, candidate_profile_id, resume_id, status, target_role, llm_provider, llm_model,
  started_at, ended_at, overall_score, readiness_score, weak_skills, metadata
)
VALUES
  (
    '88888888-8888-8888-8888-888888888881',
    '11111111-1111-1111-1111-111111111111',
    '33333333-3333-3333-3333-333333333333',
    '44444444-4444-4444-4444-444444444444',
    'completed',
    'Backend Engineer',
    'openai-compatible',
    'gpt-4o-mini',
    NOW() - INTERVAL '2 day',
    NOW() - INTERVAL '2 day' + INTERVAL '34 minute',
    68.00,
    64.00,
    '["PostgreSQL","System Design"]'::jsonb,
    '{"round":"mock-1"}'::jsonb
  );

INSERT INTO questions (
  id, session_id, question_order, question_type, source, prompt, targeted_skill_id, difficulty_level, prompt_version
)
VALUES
  (
    '99999999-9999-9999-9999-999999999991',
    '88888888-8888-8888-8888-888888888881',
    1,
    'technical',
    'llm',
    'Design an idempotent resume parse endpoint and explain failure handling.',
    1002,
    3,
    '2026.03'
  ),
  (
    '99999999-9999-9999-9999-999999999992',
    '88888888-8888-8888-8888-888888888881',
    2,
    'system_design',
    'llm',
    'How would you scale parse jobs using Redis and Celery?',
    1004,
    4,
    '2026.03'
  ),
  (
    '99999999-9999-9999-9999-999999999993',
    '88888888-8888-8888-8888-888888888881',
    3,
    'technical',
    'llm',
    'Optimize a query that tracks candidate progress over time in PostgreSQL.',
    1003,
    4,
    '2026.03'
  );

INSERT INTO responses (
  id, session_id, question_id, attempt_no, source, answer_text, is_skipped, duration_seconds, answered_at
)
VALUES
  (
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1',
    '88888888-8888-8888-8888-888888888881',
    '99999999-9999-9999-9999-999999999991',
    1,
    'text',
    'I would use idempotency keys and status tables to avoid duplicate parse executions.',
    FALSE,
    180,
    NOW() - INTERVAL '2 day' + INTERVAL '8 minute'
  ),
  (
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2',
    '88888888-8888-8888-8888-888888888881',
    '99999999-9999-9999-9999-999999999992',
    1,
    'text',
    'Redis queues with Celery workers, retries, and dead-letter handling improve reliability.',
    FALSE,
    210,
    NOW() - INTERVAL '2 day' + INTERVAL '17 minute'
  ),
  (
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa3',
    '88888888-8888-8888-8888-888888888881',
    '99999999-9999-9999-9999-999999999993',
    1,
    'text',
    'I would use covering indexes and materialized rollups for trend queries.',
    FALSE,
    245,
    NOW() - INTERVAL '2 day' + INTERVAL '27 minute'
  );

INSERT INTO evaluations (
  id, session_id, response_id, evaluation_version, evaluator, rubric_version, verdict,
  score_overall, score_breakdown, strengths, weaknesses, weak_skill_ids,
  evaluator_model, prompt_tokens, completion_tokens, latency_ms, evaluated_at
)
VALUES
  (
    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1',
    '88888888-8888-8888-8888-888888888881',
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1',
    1,
    'llm',
    'rubric-v1',
    'acceptable',
    70.00,
    '{"clarity":72,"depth":68,"tradeoffs":69}'::jsonb,
    '["Clear explanation of idempotency"]'::jsonb,
    '["Could include edge cases for partial failures"]'::jsonb,
    '{1002}',
    'gpt-4o-mini',
    520,
    150,
    1200,
    NOW() - INTERVAL '2 day' + INTERVAL '9 minute'
  ),
  (
    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2',
    '88888888-8888-8888-8888-888888888881',
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2',
    1,
    'llm',
    'rubric-v1',
    'acceptable',
    67.00,
    '{"clarity":65,"depth":68,"tradeoffs":66}'::jsonb,
    '["Good reliability instincts"]'::jsonb,
    '["Missing queue backpressure strategy"]'::jsonb,
    '{1004}',
    'gpt-4o-mini',
    600,
    165,
    1300,
    NOW() - INTERVAL '2 day' + INTERVAL '18 minute'
  ),
  (
    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb3',
    '88888888-8888-8888-8888-888888888881',
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa3',
    1,
    'llm',
    'rubric-v1',
    'needs_improvement',
    58.00,
    '{"clarity":62,"depth":54,"tradeoffs":58}'::jsonb,
    '["Mentions indexing"]'::jsonb,
    '["Needs concrete query optimization examples"]'::jsonb,
    '{1003}',
    'gpt-4o-mini',
    640,
    180,
    1450,
    NOW() - INTERVAL '2 day' + INTERVAL '28 minute'
  );

INSERT INTO recommendations (
  id, user_id, candidate_profile_id, session_id, taxonomy_skill_id, evaluation_id,
  recommendation_type, status, priority, title, recommendation_text, action_items, due_date
)
VALUES
  (
    'cccccccc-cccc-cccc-cccc-ccccccccccc1',
    '11111111-1111-1111-1111-111111111111',
    '33333333-3333-3333-3333-333333333333',
    '88888888-8888-8888-8888-888888888881',
    1003,
    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb3',
    'study_plan',
    'open',
    5,
    'Strengthen PostgreSQL performance design',
    'Practice three query optimization drills with EXPLAIN ANALYZE and summarize tradeoffs.',
    '["Build one slow query case","Add two indexes and compare plan","Document learnings"]'::jsonb,
    CURRENT_DATE + 10
  ),
  (
    'cccccccc-cccc-cccc-cccc-ccccccccccc2',
    '11111111-1111-1111-1111-111111111111',
    '33333333-3333-3333-3333-333333333333',
    '88888888-8888-8888-8888-888888888881',
    1004,
    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2',
    'mock_interview',
    'open',
    4,
    'Queue design mock round',
    'Run a focused 20-minute system design interview on queue backpressure and retries.',
    '["Design retry strategy","Add dead-letter handling","Explain monitoring"]'::jsonb,
    CURRENT_DATE + 7
  );

INSERT INTO progress_snapshots (
  id, user_id, candidate_profile_id, session_id, snapshot_date, target_role,
  readiness_score, confidence_score, weak_skill_count, weak_skills, metrics, created_at
)
VALUES
  (
    'dddddddd-dddd-dddd-dddd-ddddddddddd1',
    '11111111-1111-1111-1111-111111111111',
    '33333333-3333-3333-3333-333333333333',
    NULL,
    CURRENT_DATE - 14,
    'Backend Engineer',
    58.00,
    61.00,
    3,
    '["PostgreSQL","System Design","Redis"]'::jsonb,
    '{"sessions_completed":0,"resume_confidence":87}'::jsonb,
    NOW() - INTERVAL '14 day'
  ),
  (
    'dddddddd-dddd-dddd-dddd-ddddddddddd2',
    '11111111-1111-1111-1111-111111111111',
    '33333333-3333-3333-3333-333333333333',
    '88888888-8888-8888-8888-888888888881',
    CURRENT_DATE - 2,
    'Backend Engineer',
    64.00,
    68.00,
    2,
    '["PostgreSQL","System Design"]'::jsonb,
    '{"sessions_completed":1,"overall_score":68}'::jsonb,
    NOW() - INTERVAL '2 day'
  );

INSERT INTO progress_snapshot_skills (snapshot_id, taxonomy_skill_id, score, delta_from_prev, is_weak)
VALUES
  ('dddddddd-dddd-dddd-dddd-ddddddddddd1', 1001, 73.00, NULL, FALSE),
  ('dddddddd-dddd-dddd-dddd-ddddddddddd1', 1002, 68.00, NULL, FALSE),
  ('dddddddd-dddd-dddd-dddd-ddddddddddd1', 1003, 51.00, NULL, TRUE),
  ('dddddddd-dddd-dddd-dddd-ddddddddddd1', 1004, 54.00, NULL, TRUE),
  ('dddddddd-dddd-dddd-dddd-ddddddddddd2', 1001, 77.00, 4.00, FALSE),
  ('dddddddd-dddd-dddd-dddd-ddddddddddd2', 1002, 72.00, 4.00, FALSE),
  ('dddddddd-dddd-dddd-dddd-ddddddddddd2', 1003, 58.00, 7.00, TRUE),
  ('dddddddd-dddd-dddd-dddd-ddddddddddd2', 1004, 59.00, 5.00, TRUE);

INSERT INTO audit_logs (
  actor_user_id, actor_role, action, entity_table, entity_id, request_id, status_code,
  ip_address, user_agent, pii_fields, old_data, new_data, retention_class
)
VALUES
  (
    '11111111-1111-1111-1111-111111111111',
    'candidate',
    'upload_resume',
    'resumes',
    '44444444-4444-4444-4444-444444444444',
    'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
    201,
    '10.10.10.10',
    'Mozilla/5.0',
    '["email","storage_uri"]'::jsonb,
    NULL,
    '{"status":"uploaded"}'::jsonb,
    'sensitive'
  );

COMMIT;

-- =========================
-- Query examples
-- =========================

-- 1) Latest session report for one candidate profile
-- Replace :candidate_profile_id with your UUID
SELECT
  s.id AS session_id,
  s.target_role,
  s.status,
  s.started_at,
  s.ended_at,
  s.overall_score,
  s.readiness_score,
  COUNT(DISTINCT q.id) AS question_count,
  COUNT(DISTINCT r.id) AS response_count,
  ROUND(AVG(e.score_overall)::numeric, 2) AS avg_response_score,
  COALESCE(
    JSONB_AGG(DISTINCT rec.title) FILTER (WHERE rec.id IS NOT NULL),
    '[]'::jsonb
  ) AS recommendation_titles
FROM interview_sessions s
LEFT JOIN questions q ON q.session_id = s.id
LEFT JOIN responses r ON r.session_id = s.id
LEFT JOIN evaluations e ON e.session_id = s.id
LEFT JOIN recommendations rec ON rec.session_id = s.id
WHERE s.candidate_profile_id = :candidate_profile_id
GROUP BY s.id
ORDER BY s.started_at DESC NULLS LAST
LIMIT 1;

-- 2) Weak skills trend over time
-- Replace :candidate_profile_id with your UUID
SELECT
  ps.snapshot_date,
  st.canonical_name AS skill,
  pss.score,
  pss.delta_from_prev,
  pss.is_weak
FROM progress_snapshots ps
JOIN progress_snapshot_skills pss ON pss.snapshot_id = ps.id
JOIN skill_taxonomy st ON st.id = pss.taxonomy_skill_id
WHERE ps.candidate_profile_id = :candidate_profile_id
  AND pss.is_weak = TRUE
ORDER BY ps.snapshot_date ASC, st.canonical_name ASC;

-- 3) Role readiness over time
-- Replace :candidate_profile_id with your UUID
SELECT
  ps.snapshot_date,
  ps.target_role,
  ps.readiness_score,
  ps.confidence_score,
  ps.weak_skill_count,
  (ps.metrics ->> 'sessions_completed')::INT AS sessions_completed
FROM progress_snapshots ps
WHERE ps.candidate_profile_id = :candidate_profile_id
ORDER BY ps.snapshot_date ASC;
