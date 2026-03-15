from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from resume_parser.api import router as resume_router


app = FastAPI(
	title="AI Technical Interview Trainer - Resume Parser",
	version="0.1.0",
	description="MVP resume parsing service with confidence scoring and human-in-the-loop correction.",
)


@app.get("/health")
def health() -> dict[str, str]:
	return {"status": "ok"}


app.include_router(resume_router)


_FRONTEND_DIR = Path(__file__).parent / "frontend"
app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
