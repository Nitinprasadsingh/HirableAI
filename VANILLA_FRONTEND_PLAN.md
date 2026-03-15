# AI Technical Interview Trainer - Vanilla Frontend Architecture

Last updated: 2026-03-15

## 1) Updated System Architecture (Vanilla Frontend)

- Frontend: static HTML + CSS + vanilla JavaScript modules.
- Backend API: FastAPI (Python), serving both API routes and static pages.
- Data store: PostgreSQL (structured candidate, resume, interview, score tables).
- Queue and workers: Redis + Celery for parse jobs and evaluation jobs.
- File storage: S3-compatible object storage for uploaded resume files.
- LLM layer: OpenAI-compatible API for question generation and answer evaluation.
- Optional vector search: pgvector for semantic retrieval over projects/experience.

Flow:
1. Candidate uploads resume from static upload page.
2. FastAPI stores file metadata in DB and file in object storage.
3. Celery worker parses resume into structured profile.
4. Frontend polls parse status endpoint.
5. Interview page requests personalized questions.
6. Candidate submits answers; backend evaluates with rubric + LLM.
7. Dashboard page reads scores, weak areas, and recommendations.

## 2) Frontend File and Folder Structure

Use a multi-page static frontend:

- frontend/
  - index.html
  - upload.html
  - interview.html
  - dashboard.html
  - css/
    - styles.css
  - js/
    - api.js
    - state.js
    - ui.js
    - upload.js
    - interview.js
    - dashboard.js

## 3) API Integration with fetch

- Keep one shared fetch wrapper in js/api.js.
- Use JSON request/response for all non-upload endpoints.
- Use FormData for upload endpoint.
- Always handle:
  - HTTP non-2xx errors
  - network failures
  - invalid/missing JSON
- Keep credentials option enabled if using cookie-based auth.

## 4) Auth and Session Handling (Vanilla JS)

Recommended production pattern:
- Login endpoint issues secure, HttpOnly, SameSite cookie.
- Frontend calls fetch with credentials include.
- Access control is enforced on backend; frontend only handles UI state.
- Session timeout and refresh token handled by backend endpoints.

MVP-friendly pattern in this scaffold:
- sessionStorage stores active resume_id and current UI session state.
- localStorage stores interview report snapshots for quick local dashboard preview.

## 5) Reusable JavaScript Module Pattern

- api.js: all network calls.
- state.js: session and report persistence helpers.
- ui.js: shared DOM helpers and status rendering.
- page scripts:
  - upload.js: upload + parse polling
  - interview.js: adaptive question round + local rubric fallback
  - dashboard.js: parsed profile + chart + recommendations

## 6) Dashboard Implementation Plan

- Primary data:
  - parsed resume profile and confidence signals
  - interview evaluation report
- Visual blocks:
  - profile snapshot card
  - skill confidence chart (Chart.js)
  - weak area list (parser + interview)
  - recommendations list
- Next enhancement:
  - progress trend chart across multiple interview rounds
  - filters by role and domain

## 7) Build and Deploy Approach

Development:
- Run FastAPI app and serve frontend statically from frontend directory.
- Frontend and API share same host and port, so no CORS complexity.

Production:
- Option A: FastAPI serves static files directly.
- Option B: Nginx/CDN serves static frontend, reverse proxy API to FastAPI.
- Store resumes in S3/object storage.
- Run background workers (Celery) separately from API process.

## 8) Revised 6-Week MVP Plan

Week 1:
- Finalize DB schema and storage flow.
- Complete upload and parse API hardening.
- Ship static upload page + parse status polling.

Week 2:
- Improve parser quality and confidence logic.
- Add correction workflow and confirmation UX.
- Add parser regression test cases for sample resumes.

Week 3:
- Add interview session APIs and LLM question generation.
- Implement vanilla interview page integration.
- Add answer persistence model.

Week 4:
- Build rubric evaluator service and score breakdown.
- Add adaptive follow-up logic based on weak topics.
- Save per-question and per-round evaluation metrics.

Week 5:
- Build dashboard API endpoints.
- Implement dashboard visualizations and recommendations.
- Add charting and trend baseline.

Week 6:
- End-to-end QA, error handling, and logging.
- Add authentication and role-based access checks.
- Deployment setup for API, workers, database, and static frontend.
