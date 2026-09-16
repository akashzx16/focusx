from datetime import date, datetime, timedelta

import os
from functools import wraps

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from models import get_db, init_db, DAILY_GOAL_MINUTES, today_str, now_str
from scheduler import compute_review_update

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FOCUSX_SECRET_KEY", "change-this-focusx-secret-before-deploying")
init_db()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def get_or_create_topic(conn, user_id, name):
    row = conn.execute("SELECT * FROM topics WHERE user_id = ? AND name = ?", (user_id, name)).fetchone()
    if row:
        return row
    conn.execute(
        "INSERT INTO topics (name, first_studied_at, next_review_at, review_interval_days, review_count) "
        "VALUES (?, ?, ?, ?, 1, 0)",
        (user_id, name, now_str(), (date.today() + timedelta(days=1)).isoformat()),
    )
    conn.commit()
    return conn.execute("SELECT * FROM topics WHERE user_id = ? AND name = ?", (user_id, name)).fetchone()


def roll_daily_progress(conn, user_id, day, minutes_to_add):
    row = conn.execute("SELECT * FROM daily_progress WHERE user_id = ? AND date = ?", (user_id, day)).fetchone()
    if row:
        total = row["total_minutes"] + minutes_to_add
    else:
        total = minutes_to_add

    goal_met = 1 if total >= DAILY_GOAL_MINUTES else 0
    surplus = max(0, total - DAILY_GOAL_MINUTES)

    conn.execute(
        "INSERT INTO daily_progress (user_id, date, total_minutes, goal_met, surplus_minutes_earned) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id, date) DO UPDATE SET total_minutes = ?, goal_met = ?, surplus_minutes_earned = ?",
        (user_id, day, total, goal_met, surplus, total, goal_met, surplus),
    )
    conn.commit()
    return total, goal_met, surplus


def update_streak(conn, user_id, day, goal_met, surplus_minutes):
    state = conn.execute("SELECT * FROM streak_state WHERE user_id = ?", (user_id,)).fetchone()
    current_streak = state["current_streak"]
    banked = state["banked_minutes"]
    last_active = state["last_active_date"]

    if goal_met:
        # first time today's goal is met -> bump streak once per day
        if last_active != day:
            current_streak += 1
        # bank any surplus beyond the goal
        banked += surplus_minutes
        last_active = day

    conn.execute(
        "UPDATE streak_state SET current_streak = ?, banked_minutes = ?, last_active_date = ? WHERE user_id = ?",
        (current_streak, banked, last_active, user_id),
    )
    conn.commit()


@app.route("/")
def dashboard():
    if "user_id" not in session:
        return render_template("home.html")
    conn = get_db()
    today = today_str()
    user_id = session["user_id"]

    due_topics = conn.execute(
        "SELECT * FROM topics WHERE user_id = ? AND next_review_at <= ? ORDER BY next_review_at ASC",
        (user_id, today),
    ).fetchall()

    progress_row = conn.execute("SELECT * FROM daily_progress WHERE user_id = ? AND date = ?", (user_id, today)).fetchone()
    today_minutes = progress_row["total_minutes"] if progress_row else 0

    streak = conn.execute("SELECT * FROM streak_state WHERE user_id = ?", (user_id,)).fetchone()

    active_session = conn.execute(
        "SELECT * FROM sessions WHERE user_id = ? AND ended_at IS NULL ORDER BY id DESC LIMIT 1", (user_id,)
    ).fetchone()
    recent_sessions = conn.execute(
        "SELECT * FROM sessions WHERE user_id = ? AND ended_at IS NOT NULL ORDER BY ended_at DESC LIMIT 8", (user_id,)
    ).fetchall()

    conn.close()
    return render_template(
        "dashboard.html",
        due_topics=due_topics,
        today_minutes=today_minutes,
        daily_goal=DAILY_GOAL_MINUTES,
        streak=streak,
        active_session=active_session,
        recent_sessions=recent_sessions,
    )


@app.route("/session/start", methods=["POST"])
@login_required
def session_start():
    # topic is optional -- often you only know what you actually studied
    # partway through or at the end, so it can be filled in or edited later
    topic = request.form.get("topic", "").strip()
    try:
        duration = int(request.form.get("duration", 45))
    except ValueError:
        duration = 45
    duration = max(1, duration)

    conn = get_db()
    conn.execute(
        "INSERT INTO sessions (user_id, topic, planned_duration_minutes, started_at) VALUES (?, ?, ?, ?)",
        (session["user_id"], topic, duration, now_str()),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("session_active"))


@app.route("/session/update_topic", methods=["POST"])
@login_required
def session_update_topic():
    topic = request.form.get("topic", "").strip()
    conn = get_db()
    session_row = conn.execute(
        "SELECT * FROM sessions WHERE user_id = ? AND ended_at IS NULL ORDER BY id DESC LIMIT 1", (session["user_id"],)
    ).fetchone()
    if session_row:
        conn.execute("UPDATE sessions SET topic = ? WHERE id = ?", (topic, session_row["id"]))
        conn.commit()
    conn.close()
    return redirect(url_for("session_active"))


@app.route("/session/active")
@login_required
def session_active():
    conn = get_db()
    session_row = conn.execute(
        "SELECT * FROM sessions WHERE user_id = ? AND ended_at IS NULL ORDER BY id DESC LIMIT 1", (session["user_id"],)
    ).fetchone()
    conn.close()
    if not session_row:
        return redirect(url_for("dashboard"))
    return render_template("session.html", session=session_row)


@app.route("/session/end", methods=["POST"])
@login_required
def session_end():
    conn = get_db()
    session_row = conn.execute(
        "SELECT * FROM sessions WHERE user_id = ? AND ended_at IS NULL ORDER BY id DESC LIMIT 1", (session["user_id"],)
    ).fetchone()

    if session_row:
        # topic may be finalized right at end time, since it's often only clear by now
        final_topic = request.form.get("topic", "").strip() or session_row["topic"] or "Untitled session"

        started = datetime.fromisoformat(session_row["started_at"])
        ended = datetime.now()
        duration_minutes = max(1, round((ended - started).total_seconds() / 60))

        conn.execute(
            "UPDATE sessions SET topic = ?, ended_at = ?, duration_minutes = ? WHERE id = ?",
            (final_topic, ended.isoformat(timespec="seconds"), duration_minutes, session_row["id"]),
        )
        conn.commit()

        # make sure this topic exists in the topics table for spaced repetition
        get_or_create_topic(conn, session["user_id"], final_topic)

        today = today_str()
        total, goal_met, surplus = roll_daily_progress(conn, session["user_id"], today, duration_minutes)
        update_streak(conn, session["user_id"], today, goal_met, surplus)

    conn.close()
    return redirect(url_for("dashboard"))


@app.route("/sessions/clear", methods=["POST"])
@login_required
def sessions_clear():
    """Delete only the signed-in user's completed session history."""
    conn = get_db()
    conn.execute(
        "DELETE FROM sessions WHERE user_id = ? AND ended_at IS NOT NULL",
        (session["user_id"],),
    )
    conn.commit()
    conn.close()
    flash("Your completed session history has been cleared.")
    return redirect(url_for("dashboard"))


@app.route("/review/<int:topic_id>/complete", methods=["POST"])
@login_required
def review_complete(topic_id):
    conn = get_db()
    topic_row = conn.execute("SELECT * FROM topics WHERE id = ? AND user_id = ?", (topic_id, session["user_id"])).fetchone()
    if topic_row:
        new_interval, new_next_review_at, new_review_count = compute_review_update(topic_row)
        conn.execute(
            "UPDATE topics SET review_interval_days = ?, next_review_at = ?, "
            "review_count = ?, last_reviewed_at = ? WHERE id = ?",
            (new_interval, new_next_review_at, new_review_count, now_str(), topic_id),
        )
        conn.commit()
    conn.close()
    return redirect(url_for("dashboard"))


@app.route("/streak/spend", methods=["POST"])
@login_required
def streak_spend():
    conn = get_db()
    state = conn.execute("SELECT * FROM streak_state WHERE user_id = ?", (session["user_id"],)).fetchone()
    minutes_needed = DAILY_GOAL_MINUTES
    if state["banked_minutes"] >= minutes_needed:
        conn.execute(
            "UPDATE streak_state SET banked_minutes = ?, current_streak = current_streak + 1, "
            "last_active_date = ? WHERE user_id = ?",
            (state["banked_minutes"] - minutes_needed, today_str(), session["user_id"]),
        )
        conn.commit()
    conn.close()
    return redirect(url_for("dashboard"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or len(password) < 8:
            flash("Enter your name, a valid email, and a password of at least 8 characters.")
        else:
            conn = get_db()
            try:
                cursor = conn.execute("INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                                      (name, email, generate_password_hash(password), now_str()))
                user_id = cursor.lastrowid
                # Let the first account claim any data created in the former
                # single-user version; later accounts always start fresh.
                account_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                if account_count == 1:
                    conn.execute("UPDATE sessions SET user_id = ? WHERE user_id IS NULL", (user_id,))
                    conn.execute("UPDATE topics SET user_id = ? WHERE user_id IS NULL", (user_id,))
                    conn.execute("UPDATE daily_progress SET user_id = ? WHERE user_id IS NULL", (user_id,))
                    conn.execute("UPDATE streak_state SET user_id = ? WHERE user_id IS NULL", (user_id,))
                if not conn.execute("SELECT 1 FROM streak_state WHERE user_id = ?", (user_id,)).fetchone():
                    conn.execute("INSERT INTO streak_state (user_id) VALUES (?)", (user_id,))
                conn.commit()
                session.clear()
                session["user_id"] = user_id
                session["user_name"] = name
                return redirect(url_for("dashboard"))
            except Exception as error:
                conn.rollback()
                flash("An account with that email already exists.")
            finally:
                conn.close()
    return render_template("auth.html", mode="signup")


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("dashboard"))
        flash("Email or password is incorrect.")
    return render_template("auth.html", mode="login")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(
        debug=os.environ.get("FLASK_DEBUG") == "1",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
    )
