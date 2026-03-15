from __future__ import annotations

import argparse
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RetentionAction:
    name: str
    count_sql: str
    apply_sql: str
    params: dict[str, int | str]


def _connect(database_url: str):
    try:
        import psycopg  # pyright: ignore[reportMissingImports]
    except ModuleNotFoundError as exc:
        raise RuntimeError("psycopg is required. Install dependencies from requirements.txt") from exc

    return psycopg.connect(database_url)


def _read_months(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer number of months") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _build_actions() -> list[RetentionAction]:
    resume_months = _read_months("RETENTION_RESUME_MONTHS", 12)
    response_months = _read_months("RETENTION_RESPONSE_MONTHS", 18)
    recommendation_months = _read_months("RETENTION_RECOMMENDATION_MONTHS", 24)
    progress_months = _read_months("RETENTION_PROGRESS_MONTHS", 24)
    deleted_resume_hard_delete_months = _read_months("RETENTION_DELETED_RESUME_MONTHS", 3)

    audit_standard_months = _read_months("RETENTION_AUDIT_STANDARD_MONTHS", 12)
    audit_sensitive_months = _read_months("RETENTION_AUDIT_SENSITIVE_MONTHS", 24)
    audit_restricted_months = _read_months("RETENTION_AUDIT_RESTRICTED_MONTHS", 36)

    return [
        RetentionAction(
            name="resume_pii_anonymization",
            count_sql="""
                SELECT COUNT(*)
                FROM resumes
                WHERE uploaded_at < NOW() - make_interval(months => %(months)s)
                  AND (
                    parsed_payload IS NOT NULL
                    OR resume_embedding IS NOT NULL
                    OR status <> 'archived'::resume_status
                  )
            """,
            apply_sql="""
                UPDATE resumes
                SET parsed_payload = NULL,
                    resume_embedding = NULL,
                    status = 'archived'::resume_status,
                    updated_at = NOW()
                WHERE uploaded_at < NOW() - make_interval(months => %(months)s)
                  AND (
                    parsed_payload IS NOT NULL
                    OR resume_embedding IS NOT NULL
                    OR status <> 'archived'::resume_status
                  )
            """,
            params={"months": resume_months},
        ),
        RetentionAction(
            name="response_text_anonymization",
            count_sql="""
                SELECT COUNT(*)
                FROM responses
                WHERE answered_at < NOW() - make_interval(months => %(months)s)
                  AND (
                    answer_text IS NOT NULL
                    OR answer_audio_uri IS NOT NULL
                    OR answer_embedding IS NOT NULL
                  )
            """,
            apply_sql="""
                UPDATE responses
                SET answer_text = NULL,
                    answer_audio_uri = NULL,
                    answer_embedding = NULL
                WHERE answered_at < NOW() - make_interval(months => %(months)s)
                  AND (
                    answer_text IS NOT NULL
                    OR answer_audio_uri IS NOT NULL
                    OR answer_embedding IS NOT NULL
                  )
            """,
            params={"months": response_months},
        ),
        RetentionAction(
            name="delete_completed_recommendations",
            count_sql="""
                SELECT COUNT(*)
                FROM recommendations
                WHERE generated_at < NOW() - make_interval(months => %(months)s)
                  AND status IN ('completed', 'dismissed')
            """,
            apply_sql="""
                DELETE FROM recommendations
                WHERE generated_at < NOW() - make_interval(months => %(months)s)
                  AND status IN ('completed', 'dismissed')
            """,
            params={"months": recommendation_months},
        ),
        RetentionAction(
            name="delete_old_progress_snapshots",
            count_sql="""
                SELECT COUNT(*)
                FROM progress_snapshots
                WHERE snapshot_date < CURRENT_DATE - make_interval(months => %(months)s)
            """,
            apply_sql="""
                DELETE FROM progress_snapshots
                WHERE snapshot_date < CURRENT_DATE - make_interval(months => %(months)s)
            """,
            params={"months": progress_months},
        ),
        RetentionAction(
            name="delete_soft_deleted_resumes",
            count_sql="""
                SELECT COUNT(*)
                FROM resumes
                WHERE deleted_at IS NOT NULL
                  AND deleted_at < NOW() - make_interval(months => %(months)s)
            """,
            apply_sql="""
                DELETE FROM resumes
                WHERE deleted_at IS NOT NULL
                  AND deleted_at < NOW() - make_interval(months => %(months)s)
            """,
            params={"months": deleted_resume_hard_delete_months},
        ),
        RetentionAction(
            name="delete_audit_logs_standard",
            count_sql="""
                SELECT COUNT(*)
                FROM audit_logs
                WHERE retention_class = 'standard'
                  AND occurred_at < NOW() - make_interval(months => %(months)s)
            """,
            apply_sql="""
                DELETE FROM audit_logs
                WHERE retention_class = 'standard'
                  AND occurred_at < NOW() - make_interval(months => %(months)s)
            """,
            params={"months": audit_standard_months},
        ),
        RetentionAction(
            name="delete_audit_logs_sensitive",
            count_sql="""
                SELECT COUNT(*)
                FROM audit_logs
                WHERE retention_class = 'sensitive'
                  AND occurred_at < NOW() - make_interval(months => %(months)s)
            """,
            apply_sql="""
                DELETE FROM audit_logs
                WHERE retention_class = 'sensitive'
                  AND occurred_at < NOW() - make_interval(months => %(months)s)
            """,
            params={"months": audit_sensitive_months},
        ),
        RetentionAction(
            name="delete_audit_logs_restricted",
            count_sql="""
                SELECT COUNT(*)
                FROM audit_logs
                WHERE retention_class = 'restricted'
                  AND occurred_at < NOW() - make_interval(months => %(months)s)
            """,
            apply_sql="""
                DELETE FROM audit_logs
                WHERE retention_class = 'restricted'
                  AND occurred_at < NOW() - make_interval(months => %(months)s)
            """,
            params={"months": audit_restricted_months},
        ),
    ]


def run_retention_job(database_url: str, *, dry_run: bool = True) -> list[tuple[str, int]]:
    actions = _build_actions()
    results: list[tuple[str, int]] = []

    with _connect(database_url) as conn:
        with conn.cursor() as cur:
            for action in actions:
                if dry_run:
                    cur.execute(action.count_sql, action.params)
                    affected = int(cur.fetchone()[0])
                else:
                    cur.execute(action.apply_sql, action.params)
                    affected = int(cur.rowcount)

                results.append((action.name, affected))

        if dry_run:
            conn.rollback()
        else:
            conn.commit()

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run PII retention cleanup for AI Interview Trainer.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply retention changes. Default mode is dry-run.",
    )

    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")

    dry_run = not args.apply
    mode = "DRY-RUN" if dry_run else "APPLY"

    print(f"Retention job mode: {mode}")
    results = run_retention_job(database_url, dry_run=dry_run)

    total = 0
    for name, affected in results:
        total += affected
        print(f"- {name}: {affected}")

    print(f"Total affected rows: {total}")


if __name__ == "__main__":
    main()
