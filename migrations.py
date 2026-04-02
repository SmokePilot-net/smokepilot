import os
import glob
import sqlite3
from config import DATABASE

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")


def get_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def ensure_schema_version_table(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            filename TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.commit()


def get_current_version(db):
    try:
        row = db.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
        return row["v"] or 0
    except sqlite3.OperationalError:
        return 0


def run_migrations():
    """Run all pending migrations in order."""
    db = get_db()
    ensure_schema_version_table(db)
    current = get_current_version(db)

    migration_files = sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.sql")))
    applied = 0

    for filepath in migration_files:
        filename = os.path.basename(filepath)
        # Extract version number from filename (e.g., "001_initial.sql" -> 1)
        try:
            version = int(filename.split("_")[0])
        except (ValueError, IndexError):
            continue

        if version <= current:
            continue

        with open(filepath, "r") as f:
            sql = f.read()

        try:
            db.executescript(sql)
            db.execute(
                "INSERT INTO schema_version (version, filename) VALUES (?, ?)",
                (version, filename)
            )
            db.commit()
            applied += 1
            print(f"  Applied migration: {filename}")
        except Exception as e:
            print(f"  Migration failed ({filename}): {e}")
            db.rollback()
            raise

    db.close()

    if applied:
        print(f"  {applied} migration(s) applied")
    return applied
