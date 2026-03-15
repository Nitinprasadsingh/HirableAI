"""Initialize PostgreSQL schema for AI Interview Trainer.

Revision ID: 20260315_0001
Revises:
Create Date: 2026-03-15
"""

from __future__ import annotations

from pathlib import Path
import re

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260315_0001"
down_revision = None
branch_labels = None
depends_on = None


def _load_schema_ddl() -> str:
    root_dir = Path(__file__).resolve().parents[3]
    schema_path = root_dir / "database" / "postgres_schema.sql"
    raw_sql = schema_path.read_text(encoding="utf-8")

    seed_marker = "-- =========================\n-- Example seed data"
    ddl_sql = raw_sql.split(seed_marker, 1)[0]

    ddl_sql = ddl_sql.replace("BEGIN;", "", 1)
    ddl_sql = ddl_sql.replace("COMMIT;", "")

    return ddl_sql.strip() + "\n"


def _split_sql_statements(sql_text: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []

    in_single = False
    in_double = False
    dollar_tag: str | None = None
    in_line_comment = False
    in_block_comment = False

    i = 0
    length = len(sql_text)

    while i < length:
        ch = sql_text[i]
        nxt = sql_text[i + 1] if i + 1 < length else ""

        if in_line_comment:
            buffer.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            buffer.append(ch)
            if ch == "*" and nxt == "/":
                buffer.append(nxt)
                i += 2
                in_block_comment = False
            else:
                i += 1
            continue

        if dollar_tag is not None:
            if sql_text.startswith(dollar_tag, i):
                buffer.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
            else:
                buffer.append(ch)
                i += 1
            continue

        if not in_single and not in_double:
            if ch == "-" and nxt == "-":
                buffer.append(ch)
                buffer.append(nxt)
                i += 2
                in_line_comment = True
                continue

            if ch == "/" and nxt == "*":
                buffer.append(ch)
                buffer.append(nxt)
                i += 2
                in_block_comment = True
                continue

            if ch == "$":
                tag_match = re.match(r"\$[A-Za-z0-9_]*\$", sql_text[i:])
                if tag_match:
                    tag = tag_match.group(0)
                    buffer.append(tag)
                    i += len(tag)
                    dollar_tag = tag
                    continue

        if ch == "'" and not in_double:
            if in_single and nxt == "'":
                buffer.append(ch)
                buffer.append(nxt)
                i += 2
                continue
            in_single = not in_single
            buffer.append(ch)
            i += 1
            continue

        if ch == '"' and not in_single:
            if in_double and nxt == '"':
                buffer.append(ch)
                buffer.append(nxt)
                i += 2
                continue
            in_double = not in_double
            buffer.append(ch)
            i += 1
            continue

        if ch == ";" and not in_single and not in_double:
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
            i += 1
            continue

        buffer.append(ch)
        i += 1

    trailing = "".join(buffer).strip()
    if trailing:
        statements.append(trailing)

    return statements


def upgrade() -> None:
    ddl_sql = _load_schema_ddl()
    for statement in _split_sql_statements(ddl_sql):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS progress_snapshot_skills CASCADE")
    op.execute("DROP TABLE IF EXISTS progress_snapshots CASCADE")
    op.execute("DROP TABLE IF EXISTS recommendations CASCADE")
    op.execute("DROP TABLE IF EXISTS evaluations CASCADE")
    op.execute("DROP TABLE IF EXISTS responses CASCADE")
    op.execute("DROP TABLE IF EXISTS questions CASCADE")
    op.execute("DROP TABLE IF EXISTS interview_sessions CASCADE")
    op.execute("DROP TABLE IF EXISTS experiences CASCADE")
    op.execute("DROP TABLE IF EXISTS projects CASCADE")
    op.execute("DROP TABLE IF EXISTS skills CASCADE")
    op.execute("DROP TABLE IF EXISTS skill_aliases CASCADE")
    op.execute("DROP TABLE IF EXISTS skill_taxonomy CASCADE")
    op.execute("DROP TABLE IF EXISTS skill_categories CASCADE")
    op.execute("DROP TABLE IF EXISTS resumes CASCADE")
    op.execute("DROP TABLE IF EXISTS candidate_profiles CASCADE")
    op.execute("DROP TABLE IF EXISTS users CASCADE")

    op.execute("DROP FUNCTION IF EXISTS set_updated_at() CASCADE")

    op.execute("DROP TYPE IF EXISTS pii_retention_class CASCADE")
    op.execute("DROP TYPE IF EXISTS audit_action CASCADE")
    op.execute("DROP TYPE IF EXISTS recommendation_status CASCADE")
    op.execute("DROP TYPE IF EXISTS recommendation_type CASCADE")
    op.execute("DROP TYPE IF EXISTS evaluation_verdict CASCADE")
    op.execute("DROP TYPE IF EXISTS evaluator_type CASCADE")
    op.execute("DROP TYPE IF EXISTS response_source CASCADE")
    op.execute("DROP TYPE IF EXISTS question_source CASCADE")
    op.execute("DROP TYPE IF EXISTS question_type CASCADE")
    op.execute("DROP TYPE IF EXISTS session_status CASCADE")
    op.execute("DROP TYPE IF EXISTS resume_status CASCADE")
    op.execute("DROP TYPE IF EXISTS user_role CASCADE")
