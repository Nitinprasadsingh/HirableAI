from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from .config import settings


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS resumes (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    consent_version TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    parsed_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS parse_jobs (
                    id TEXT PRIMARY KEY,
                    resume_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    stage TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(resume_id) REFERENCES resumes(id)
                );

                CREATE TABLE IF NOT EXISTS corrections (
                    id TEXT PRIMARY KEY,
                    resume_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(resume_id) REFERENCES resumes(id)
                );

                CREATE TABLE IF NOT EXISTS answer_evaluations (
                    id TEXT PRIMARY KEY,
                    resume_id TEXT,
                    session_id TEXT,
                    question_id TEXT,
                    question TEXT NOT NULL,
                    target_role TEXT,
                    experience_level TEXT,
                    focus_topic TEXT,
                    difficulty INTEGER,
                    weighted_final_score_100 REAL NOT NULL,
                    verdict TEXT NOT NULL,
                    weak INTEGER NOT NULL,
                    missed_key_points_json TEXT NOT NULL,
                    adaptive_follow_up_prompts_json TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(resume_id) REFERENCES resumes(id)
                );

                CREATE INDEX IF NOT EXISTS idx_answer_evaluations_resume_created
                    ON answer_evaluations (resume_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_answer_evaluations_session_created
                    ON answer_evaluations (session_id, created_at DESC);
                """
            )
            conn.commit()

    def create_resume(
        self,
        candidate_id: str,
        consent_version: str,
        file_path: str,
        file_type: str,
    ) -> UUID:
        resume_id = uuid4()
        now = _utc_now()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO resumes (
                        id, candidate_id, consent_version, file_path, file_type, status,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(resume_id),
                        candidate_id,
                        consent_version,
                        file_path,
                        file_type,
                        "uploaded",
                        now,
                        now,
                    ),
                )
                conn.commit()
        return resume_id

    def get_resume(self, resume_id: UUID) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM resumes WHERE id = ?", (str(resume_id),)).fetchone()
        return dict(row) if row else None

    def update_resume_status(self, resume_id: UUID, status: str) -> None:
        now = _utc_now()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE resumes SET status = ?, updated_at = ? WHERE id = ?",
                    (status, now, str(resume_id)),
                )
                conn.commit()

    def update_resume_file_path(self, resume_id: UUID, file_path: str) -> None:
        now = _utc_now()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE resumes SET file_path = ?, updated_at = ? WHERE id = ?",
                    (file_path, now, str(resume_id)),
                )
                conn.commit()

    def create_parse_job(self, resume_id: UUID) -> UUID:
        job_id = uuid4()
        now = _utc_now()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO parse_jobs (
                        id, resume_id, status, progress, stage, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (str(job_id), str(resume_id), "queued", 0, "queued", now, now),
                )
                conn.commit()
        return job_id

    def get_parse_job(self, parse_job_id: UUID) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM parse_jobs WHERE id = ?", (str(parse_job_id),)).fetchone()
        return dict(row) if row else None

    def update_parse_job(
        self,
        parse_job_id: UUID,
        *,
        status: str,
        progress: int,
        stage: str,
        error: str | None = None,
    ) -> None:
        now = _utc_now()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE parse_jobs
                    SET status = ?, progress = ?, stage = ?, error = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (status, progress, stage, error, now, str(parse_job_id)),
                )
                conn.commit()

    def save_parsed_resume(self, resume_id: UUID, parsed_payload: dict[str, Any], status: str) -> None:
        now = _utc_now()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE resumes
                    SET parsed_json = ?, status = ?, version = version + 1, updated_at = ?
                    WHERE id = ?
                    """,
                    (json.dumps(parsed_payload), status, now, str(resume_id)),
                )
                conn.commit()

    def get_parsed_resume(self, resume_id: UUID) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT parsed_json, status, version FROM resumes WHERE id = ?",
                (str(resume_id),),
            ).fetchone()
        if not row or not row["parsed_json"]:
            return None
        parsed = json.loads(row["parsed_json"])
        parsed["status"] = row["status"]
        parsed["version"] = row["version"]
        return parsed

    def apply_corrections(
        self,
        resume_id: UUID,
        *,
        current_version: int,
        corrections: list[dict[str, Any]],
        parsed_payload: dict[str, Any],
        status: str,
    ) -> int:
        resume = self.get_resume(resume_id)
        if not resume:
            raise ValueError("resume_not_found")
        if int(resume["version"]) != current_version:
            raise RuntimeError("version_conflict")

        now = _utc_now()
        with self._lock:
            with self._connect() as conn:
                for correction in corrections:
                    conn.execute(
                        """
                        INSERT INTO corrections (id, resume_id, path, old_value, new_value, reason, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid4()),
                            str(resume_id),
                            correction["path"],
                            json.dumps(correction.get("old_value")),
                            json.dumps(correction.get("new_value")),
                            correction["reason"],
                            now,
                        ),
                    )

                conn.execute(
                    """
                    UPDATE resumes
                    SET parsed_json = ?, status = ?, version = version + 1, updated_at = ?
                    WHERE id = ?
                    """,
                    (json.dumps(parsed_payload), status, now, str(resume_id)),
                )
                conn.commit()

        updated = self.get_resume(resume_id)
        if not updated:
            raise ValueError("resume_not_found")
        return int(updated["version"])

    def save_answer_evaluation(
        self,
        *,
        resume_id: UUID | None,
        session_id: str | None,
        question_id: str | None,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any],
    ) -> UUID:
        evaluation_id = uuid4()
        now = _utc_now()

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO answer_evaluations (
                        id, resume_id, session_id, question_id, question, target_role,
                        experience_level, focus_topic, difficulty, weighted_final_score_100,
                        verdict, weak, missed_key_points_json, adaptive_follow_up_prompts_json,
                        request_json, response_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(evaluation_id),
                        str(resume_id) if resume_id else None,
                        session_id,
                        question_id,
                        str(response_payload.get("question") or request_payload.get("question") or ""),
                        str(response_payload.get("target_role") or request_payload.get("target_role") or ""),
                        str(response_payload.get("experience_level") or request_payload.get("experience_level") or ""),
                        str(response_payload.get("focus_topic") or request_payload.get("focus_topic") or ""),
                        int(response_payload.get("difficulty") or request_payload.get("difficulty") or 3),
                        float(response_payload.get("weighted_final_score_100") or 0.0),
                        str(response_payload.get("verdict") or "weak"),
                        1 if bool(response_payload.get("weak")) else 0,
                        json.dumps(response_payload.get("missed_key_points") or []),
                        json.dumps(response_payload.get("adaptive_follow_up_prompts") or []),
                        json.dumps(request_payload),
                        json.dumps(response_payload),
                        now,
                    ),
                )
                conn.commit()

        return evaluation_id

    def get_recent_answer_evaluations(
        self,
        *,
        resume_id: UUID | None = None,
        session_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(50, int(limit)))

        base_sql = """
            SELECT *
            FROM answer_evaluations
        """
        where_parts: list[str] = []
        params: list[Any] = []

        if resume_id is not None:
            where_parts.append("resume_id = ?")
            params.append(str(resume_id))

        if session_id is not None:
            where_parts.append("session_id = ?")
            params.append(session_id)

        if where_parts:
            base_sql += " WHERE " + " AND ".join(where_parts)

        base_sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(safe_limit)

        with self._connect() as conn:
            rows = conn.execute(base_sql, tuple(params)).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["missed_key_points"] = json.loads(item.pop("missed_key_points_json", "[]"))
            item["adaptive_follow_up_prompts"] = json.loads(item.pop("adaptive_follow_up_prompts_json", "[]"))
            item["request"] = json.loads(item.pop("request_json", "{}"))
            item["response"] = json.loads(item.pop("response_json", "{}"))
            item["weak"] = bool(item.get("weak"))
            result.append(item)

        return result


repository = Repository(settings.db_path)
