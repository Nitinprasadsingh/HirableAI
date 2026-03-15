# Resume Parser

FastAPI-based resume parsing MVP for PDF/DOCX resumes with:
- text extraction
- section detection
- entity extraction (skills, education, projects, experience, tools)
- skill normalization
- per-field confidence scoring
- duplicate resolution
- human-in-the-loop correction endpoint

Includes a beginner-friendly frontend built with:
- HTML
- CSS
- Vanilla JavaScript modules

## Quick Start

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run API:

```bash
uvicorn app:app --reload
```

4. Open docs:
- http://127.0.0.1:8000/docs

5. Open frontend:
- http://127.0.0.1:8000/index.html
- http://127.0.0.1:8000/upload.html
- http://127.0.0.1:8000/interview.html
- http://127.0.0.1:8000/dashboard.html

## API Endpoints

- `POST /v1/resumes/upload`
- `POST /v1/resumes/{resume_id}/parse`
- `GET /v1/parse-jobs/{parse_job_id}`
- `GET /v1/resumes/{resume_id}/parsed`
- `PATCH /v1/resumes/{resume_id}/confirm`
- `POST /v1/interviews/questions`
- `GET /v1/interviews/questions/framework`
- `POST /v1/interviews/evaluate`
- `GET /v1/interviews/evaluate/framework`
- `GET /v1/interviews/evaluations/recent`
- `POST /v1/interviews/questions`
- `GET /v1/interviews/questions/framework`

## Notes

- Parsed artifacts and metadata are stored in SQLite at `data/resume_parser.db`.
- Uploaded files are stored under `data/uploads/`.
- OCR requires local Tesseract installation.

## PostgreSQL Migration Setup (Alembic)

This project now includes PostgreSQL schema migration tooling for the interview-trainer data model.

1. Set `DATABASE_URL` for your PostgreSQL instance.

```bash
set DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/ai_interview
```

2. Run initial migration:

```bash
alembic upgrade head
```

Files:
- `alembic.ini`
- `database/alembic/env.py`
- `database/alembic/versions/20260315_0001_init_postgres_schema.py`

## PII Retention Cleanup Job

Run in dry-run mode first:

```bash
python -m database.retention_job
```

Apply cleanup changes:

```bash
python -m database.retention_job --apply
```

Optional retention overrides (months):
- `RETENTION_RESUME_MONTHS` (default `12`)
- `RETENTION_RESPONSE_MONTHS` (default `18`)
- `RETENTION_RECOMMENDATION_MONTHS` (default `24`)
- `RETENTION_PROGRESS_MONTHS` (default `24`)
- `RETENTION_DELETED_RESUME_MONTHS` (default `3`)
- `RETENTION_AUDIT_STANDARD_MONTHS` (default `12`)
- `RETENTION_AUDIT_SENSITIVE_MONTHS` (default `24`)
- `RETENTION_AUDIT_RESTRICTED_MONTHS` (default `36`)

## Frontend Structure

- `frontend/index.html`
- `frontend/upload.html`
- `frontend/interview.html`
- `frontend/dashboard.html`
- `frontend/css/styles.css`
- `frontend/js/api.js`
- `frontend/js/state.js`
- `frontend/js/ui.js`
- `frontend/js/upload.js`
- `frontend/js/interview.js`
- `frontend/js/dashboard.js`

## Question Generation Engine

Technical interview question generation framework docs and examples:
- `QUESTION_GENERATION_ENGINE.md`

Implementation:
- `resume_parser/question_engine.py`
