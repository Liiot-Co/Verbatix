#!/usr/bin/env python
import os
import sys
import logging
from pathlib import Path

# Add the backend directory to sys.path to allow importing from app
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.core.database import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "db" / "migrations"

# Las mismas .sql se montan en docker-entrypoint-initdb.d (primer arranque del
# volumen). Ese camino NO escribe schema_migrations, así que al subir el
# backend hay que detectar lo ya materializado y solo registrar el ledger.
_ALREADY_PRESENT = {
    "000_local_auth_stub.sql": "select to_regclass('auth.users')",
    "001_schema_v8.sql": "select to_regclass('public.users')",
    "002_local_auth_rbac.sql": (
        "select 1 from information_schema.columns "
        "where table_schema = 'public' and table_name = 'users' "
        "and column_name = 'password_hash'"
    ),
    "002_schema_v9.sql": (
        "select 1 from information_schema.columns "
        "where table_schema = 'public' and table_name = 'respondents' "
        "and column_name = 'realid'"
    ),
    "003_notifications_reminders.sql": (
        "select 1 from information_schema.columns "
        "where table_schema = 'public' and table_name = 'notifications' "
        "and column_name = 'last_reminded_at'"
    ),
    "003_req03_backfill_imported_file.sql": (
        "select to_regclass('public.import_review_flags')"
    ),
    "004_notification_sender.sql": (
        "select 1 from information_schema.columns "
        "where table_schema = 'public' and table_name = 'notifications' "
        "and column_name = 'sender_id'"
    ),
    "004_req07_catalog_provenance.sql": (
        "select 1 from pg_trigger "
        "where tgname = 'codes_code_number_immutable'"
    ),
    "005_req08_req04_question_controls.sql": (
        "select to_regclass('public.question_mention_decisions')"
    ),
    "006_req08_req04_round_scope.sql": (
        "select 1 from information_schema.columns "
        "where table_schema = 'public' and table_name = 'rounds' "
        "and column_name = 'expected_max_mentions'"
    ),
    "007_ingestion_fidelity.sql": (
        "select 1 from information_schema.columns "
        "where table_schema = 'public' and table_name = 'verbatims' "
        "and column_name = 'mention_position'"
    ),
    "008_classification_governance.sql": (
        "select 1 from information_schema.columns "
        "where table_schema = 'public' and table_name = 'codes' "
        "and column_name = 'approval_status'"
    ),
    "009_precision_sources_and_legacy_reopen.sql": (
        "select 1 from pg_constraint "
        "where conname = 'verbatim_codes_source_check' "
        "and pg_get_constraintdef(oid) like '%llm_suggestion%'"
    ),
}


def _migration_already_materialized(conn, filename: str) -> bool:
    probe = _ALREADY_PRESENT.get(filename)
    if not probe:
        return False
    return conn.execute(text(probe)).scalar() is not None


def run_migrations():
    logger.info(f"Checking migrations in {MIGRATIONS_DIR}...")

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """))

    if not MIGRATIONS_DIR.exists():
        logger.error(f"Error: Migrations directory not found at {MIGRATIONS_DIR}")
        return

    migration_files = sorted(
        [f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql")]
    )

    migrations_run = 0
    migrations_synced = 0

    for file in migration_files:
        with engine.begin() as conn:
            result = conn.execute(
                text("SELECT 1 FROM schema_migrations WHERE version = :version"),
                {"version": file},
            )
            if result.scalar():
                continue

            if _migration_already_materialized(conn, file):
                conn.execute(
                    text("INSERT INTO schema_migrations (version) VALUES (:version);"),
                    {"version": file},
                )
                migrations_synced += 1
                logger.info(
                    f"Recording {file} as already applied "
                    "(present from initdb or a previous run)"
                )
                continue

            logger.info(f"Applying {file}...")
            file_path = MIGRATIONS_DIR / file
            with open(file_path, "r", encoding="utf-8") as f:
                # Filter out psql meta-commands that start with \ (e.g., \set)
                sql_lines = f.readlines()
                sql = "".join(
                    line for line in sql_lines if not line.lstrip().startswith("\\")
                )

            raw_conn = conn.connection.driver_connection
            with raw_conn.cursor() as cursor:
                cursor.execute(sql)

            conn.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:version);"),
                {"version": file},
            )
            migrations_run += 1
            logger.info(f"Successfully applied {file}")

    if migrations_run == 0 and migrations_synced == 0:
        logger.info("All migrations are already applied.")
    else:
        if migrations_synced:
            logger.info(f"Synced {migrations_synced} migrations already present in DB.")
        if migrations_run:
            logger.info(f"Successfully applied {migrations_run} migrations.")


if __name__ == "__main__":
    run_migrations()
