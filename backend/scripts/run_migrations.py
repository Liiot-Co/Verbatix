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
    
    for file in migration_files:
        with engine.begin() as conn:
            result = conn.execute(
                text("SELECT 1 FROM schema_migrations WHERE version = :version"),
                {"version": file}
            )
            if not result.scalar():
                logger.info(f"Applying {file}...")
                file_path = MIGRATIONS_DIR / file
                with open(file_path, "r", encoding="utf-8") as f:
                    # Filter out psql meta-commands that start with \ (e.g., \set)
                    sql_lines = f.readlines()
                    sql = "".join(line for line in sql_lines if not line.lstrip().startswith("\\"))
                
                raw_conn = conn.connection.driver_connection
                with raw_conn.cursor() as cursor:
                    cursor.execute(sql)
                
                conn.execute(
                    text("INSERT INTO schema_migrations (version) VALUES (:version);"),
                    {"version": file}
                )
                migrations_run += 1
                logger.info(f"Successfully applied {file}")
            
    if migrations_run == 0:
        logger.info("All migrations are already applied.")
    else:
        logger.info(f"Successfully applied {migrations_run} migrations.")

if __name__ == "__main__":
    run_migrations()
