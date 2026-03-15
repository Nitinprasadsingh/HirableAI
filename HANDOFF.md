# Project Handoff - Resume Parser by Opus

Last updated: 2026-03-14

## Current state

- FastAPI resume parser MVP is implemented and running.
- Core endpoints are working: upload, start parse, parse job status, parsed fetch, confirm.
- Parser improvements applied:
  - better experience entry splitting
  - better title/company/date separation
  - better education institution extraction
  - reduced short-alias false positives for skills

## Run commands (venv)

Use project venv Python:

```powershell
venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8001
```

Install dependencies:

```powershell
venv\Scripts\python.exe -m pip install -r requirements.txt
```

## API flow that works

1. Upload resume

```powershell
curl.exe -s -X POST "http://127.0.0.1:8001/v1/resumes/upload" -F "file=@accuracy_resume.docx" -F "candidate_id=test-1" -F "consent_version=v1"
```

Response includes `resume_id`.

2. Start parse (body is client-provided metadata)

```json
{
  "force_reparse": false,
  "pipeline_version": "2026.03",
  "idempotency_key": "run-001"
}
```

Call:

```powershell
$body = @{ force_reparse = $false; pipeline_version = "2026.03"; idempotency_key = ("run-" + [guid]::NewGuid().ToString()) } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri ("http://127.0.0.1:8001/v1/resumes/<resume_id>/parse") -Method Post -ContentType "application/json" -Body $body
```

3. Poll job status

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8001/v1/parse-jobs/<parse_job_id>" -Method Get
```

4. Fetch parsed profile

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8001/v1/resumes/<resume_id>/parsed" -Method Get
```

5. Confirm corrections (human-in-the-loop)

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8001/v1/resumes/<resume_id>/confirm" -Method Patch -ContentType "application/json" -Body '{"version":2,"corrections":[],"confirm_final":true}'
```

## Important notes

- `resume_id` comes from upload response.
- Parse request body does NOT come from upload response.
- 422 on start parse is usually malformed JSON in PowerShell.
- Use `ConvertTo-Json -Compress` to build body safely.
- PowerShell 5.1 does not support `Invoke-RestMethod -Form`; use `curl.exe -F` for multipart upload.

## Files of interest

- app.py
- resume_parser/api.py
- resume_parser/pipeline.py
- resume_parser/repository.py
- resume_parser/schemas.py
- requirements.txt

## Known limitations

- OCR path depends on local Tesseract installation.
- Data storage is SQLite for MVP and local testing.
- No automated regression test suite yet.

## Recommended next actions

1. Add automated parser regression tests for key entity extraction.
2. Add frontend manual-correction UI for low-confidence fields.
3. Move async parse execution to Celery + Redis for production-like behavior.
4. Add structured logs and Sentry integration for parse failures.
