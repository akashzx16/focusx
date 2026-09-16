import sqlite3
import os
from pathlib import Path
from datetime import date, datetime

# An absolute default keeps the database beside this source file even when a
# hosting provider starts the WSGI process from a different working directory.
DB_PATH = os.environ.get("FOCUSX_DB_PATH", str(Path(__file__).resolve().parent / "focusx.db"))

DAILY_GOAL_MINUTES = 60  # change this to whatever your daily goal is


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL DEFAULT '',
            planned_duration_minutes INTEGER NOT NULL DEFAULT 45,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            duration_minutes INTEGER
        );

        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            first_studied_at TEXT NOT NULL,
            last_reviewed_at TEXT,
            next_review_at TEXT NOT NULL,
            review_interval_days INTEGER NOT NULL DEFAULT 1,
            review_count INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS daily_progress (
            date TEXT PRIMARY KEY,
            total_minutes INTEGER NOT NULL DEFAULT 0,
            goal_met INTEGER NOT NULL DEFAULT 0,
            surplus_minutes_earned INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS streak_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            current_streak INTEGER NOT NULL DEFAULT 0,
            banked_minutes INTEGER NOT NULL DEFAULT 0,
            last_active_date TEXT
        );

        CREATE TABLE IF NOT EXISTS weekly_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sent_at TEXT NOT NULL,
            week_start TEXT NOT NULL,
            week_end TEXT NOT NULL
        );
        """
    )
    # migrate older databases that predate the planned_duration_minutes column
    existing_columns = [row["name"] for row in conn.execute("PRAGMA table_info(sessions)")]
    if "planned_duration_minutes" not in existing_columns:
        conn.execute(
            "ALTER TABLE sessions ADD COLUMN planned_duration_minutes INTEGER NOT NULL DEFAULT 45"
        )

    # Accounts were added after the original single-user app. Rebuild the
    # small per-user tables so their former global keys become per-user keys.
    _migrate_account_data(conn)

    conn.commit()
    conn.close()


def _migrate_account_data(conn):
    session_columns = [row["name"] for row in conn.execute("PRAGMA table_info(sessions)")]
    if "user_id" not in session_columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN user_id INTEGER REFERENCES users(id)")

    topic_columns = [row["name"] for row in conn.execute("PRAGMA table_info(topics)")]
    if "user_id" not in topic_columns:
        conn.executescript(
            """
            CREATE TABLE topics_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id),
                name TEXT NOT NULL,
                first_studied_at TEXT NOT NULL,
                last_reviewed_at TEXT,
                next_review_at TEXT NOT NULL,
                review_interval_days INTEGER NOT NULL DEFAULT 1,
                review_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, name)
            );
            INSERT INTO topics_new (id, user_id, name, first_studied_at, last_reviewed_at, next_review_at, review_interval_days, review_count)
            SELECT id, NULL, name, first_studied_at, last_reviewed_at, next_review_at, review_interval_days, review_count FROM topics;
            DROP TABLE topics;
            ALTER TABLE topics_new RENAME TO topics;
            """
        )

    progress_columns = [row["name"] for row in conn.execute("PRAGMA table_info(daily_progress)")]
    if "user_id" not in progress_columns:
        conn.executescript(
            """
            CREATE TABLE daily_progress_new (
                user_id INTEGER REFERENCES users(id),
                date TEXT NOT NULL,
                total_minutes INTEGER NOT NULL DEFAULT 0,
                goal_met INTEGER NOT NULL DEFAULT 0,
                surplus_minutes_earned INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, date)
            );
            INSERT INTO daily_progress_new (user_id, date, total_minutes, goal_met, surplus_minutes_earned)
            SELECT NULL, date, total_minutes, goal_met, surplus_minutes_earned FROM daily_progress;
            DROP TABLE daily_progress;
            ALTER TABLE daily_progress_new RENAME TO daily_progress;
            """
        )

    streak_columns = [row["name"] for row in conn.execute("PRAGMA table_info(streak_state)")]
    if "user_id" not in streak_columns:
        conn.executescript(
            """
            CREATE TABLE streak_state_new (
                user_id INTEGER UNIQUE REFERENCES users(id),
                current_streak INTEGER NOT NULL DEFAULT 0,
                banked_minutes INTEGER NOT NULL DEFAULT 0,
                last_active_date TEXT
            );
            INSERT INTO streak_state_new (user_id, current_streak, banked_minutes, last_active_date)
            SELECT NULL, current_streak, banked_minutes, last_active_date FROM streak_state WHERE id = 1;
            DROP TABLE streak_state;
            ALTER TABLE streak_state_new RENAME TO streak_state;
            """
        )


def today_str():
    return date.today().isoformat()


def now_str():
    return datetime.now().isoformat(timespec="seconds")
