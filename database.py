"""
SQLite database layer for the Loan Application system.
FOR TRAINING / PENETRATION TESTING LAB USE ONLY.
Contains an intentional SQL injection vulnerability in get_user_profile_raw().
"""

import sqlite3
from typing import Any, Dict, Optional

DB_PATH = "loan_agent.db"

SEED_USERS = [
    ("usr_alice01", "alice_eligible", "alice123", "Applier", 720, 9000.0, 1800.0, 0),
    ("usr_bob02", "bob_ineligible", "bob123", "Applier", 620, 4500.0, 2200.0, 3),
    ("usr_carol03", "carol_approver", "carol123", "Approver", 750, 12000.0, 2000.0, 0),
    ("usr_dave04", "dave_borderline", "dave123", "Applier", 650, 5500.0, 2400.0, 2),
    ("usr_admin", "admin", "admin", "Admin", 0, 0.0, 0.0, 0),
]

SEED_APPLICATIONS = [
    ("app_seed01", "usr_alice01", 15000.0, 36, "Pending", "2026-04-10T09:30:00Z", "Rate: 5.49% | Monthly payment: $452.87 | Purpose: home loan | Awaiting review."),
]


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _create_tables(cur: sqlite3.Cursor) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            password TEXT,
            role TEXT,
            credit_score INTEGER,
            gross_monthly_income REAL,
            total_monthly_debt REAL,
            late_payments_last_2_years INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            application_id TEXT PRIMARY KEY,
            user_id TEXT,
            loan_amount REAL,
            duration_months INTEGER,
            status TEXT,
            submission_timestamp TEXT,
            internal_notes TEXT,
            approved_by TEXT,
            approval_timestamp TEXT
        )
    """)


def _seed_users(cur: sqlite3.Cursor) -> None:
    cur.executemany(
        "INSERT INTO users (user_id, username, password, role, credit_score, gross_monthly_income, total_monthly_debt, late_payments_last_2_years) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        SEED_USERS,
    )


def _seed_applications(cur: sqlite3.Cursor) -> None:
    cur.executemany(
        "INSERT INTO applications (application_id, user_id, loan_amount, duration_months, status, submission_timestamp, internal_notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
        SEED_APPLICATIONS,
    )


def init_db() -> None:
    conn = get_db()
    cur = conn.cursor()
    _create_tables(cur)

    # Seed users only if the table is empty
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        _seed_users(cur)

    # Seed applications only if the table is empty
    cur.execute("SELECT COUNT(*) FROM applications")
    if cur.fetchone()[0] == 0:
        _seed_applications(cur)

    conn.commit()
    conn.close()


def reset_db() -> None:
    conn = get_db()
    cur = conn.cursor()
    _create_tables(cur)
    cur.execute("DELETE FROM applications")
    cur.execute("DELETE FROM users")
    _seed_users(cur)
    _seed_applications(cur)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Row → dict helpers
# ---------------------------------------------------------------------------

def _row_to_user_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "user_id": row["user_id"],
        "username": row["username"],
        "password": row["password"],
        "role": row["role"],
        "profile": {
            "credit_score": row["credit_score"],
            "gross_monthly_income": row["gross_monthly_income"],
            "total_monthly_debt": row["total_monthly_debt"],
            "late_payments_last_2_years": row["late_payments_last_2_years"],
        },
    }


def _row_to_application_dict(row: sqlite3.Row) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {
        "submission_timestamp": row["submission_timestamp"],
        "internal_notes": row["internal_notes"],
    }
    if row["approved_by"]:
        metadata["approved_by"] = row["approved_by"]
    if row["approval_timestamp"]:
        metadata["approval_timestamp"] = row["approval_timestamp"]

    return {
        "application_id": row["application_id"],
        "user_id": row["user_id"],
        "loan_amount": row["loan_amount"],
        "duration_months": row["duration_months"],
        "status": row["status"],
        "metadata": metadata,
    }


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_all_users() -> Dict[str, Dict[str, Any]]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM users").fetchall()
    conn.close()
    return {row["user_id"]: _row_to_user_dict(row) for row in rows}


def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    return _row_to_user_dict(row)


def get_all_applications() -> Dict[str, Dict[str, Any]]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM applications").fetchall()
    conn.close()
    return {row["application_id"]: _row_to_application_dict(row) for row in rows}


def get_application(application_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    row = conn.execute("SELECT * FROM applications WHERE application_id = ?", (application_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    return _row_to_application_dict(row)


def update_user(user_id: str, **kwargs) -> None:
    allowed = {"username", "password", "role", "credit_score", "gross_monthly_income", "total_monthly_debt", "late_payments_last_2_years"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [user_id]
    conn = get_db()
    conn.execute(f"UPDATE users SET {set_clause} WHERE user_id = ?", values)
    conn.commit()
    conn.close()


def insert_application(
    application_id: str,
    user_id: str,
    loan_amount: float,
    duration_months: int,
    status: str,
    submission_timestamp: str,
    internal_notes: str,
) -> None:
    conn = get_db()
    conn.execute(
        "INSERT INTO applications (application_id, user_id, loan_amount, duration_months, status, submission_timestamp, internal_notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (application_id, user_id, loan_amount, duration_months, status, submission_timestamp, internal_notes),
    )
    conn.commit()
    conn.close()


def update_application(application_id: str, **kwargs) -> None:
    allowed = {"status", "loan_amount", "duration_months", "submission_timestamp", "internal_notes", "approved_by", "approval_timestamp"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [application_id]
    conn = get_db()
    conn.execute(f"UPDATE applications SET {set_clause} WHERE application_id = ?", values)
    conn.commit()
    conn.close()


def insert_user(
    user_id: str,
    username: str,
    password: str,
    role: str,
    credit_score: int = 0,
    gross_monthly_income: float = 0.0,
    total_monthly_debt: float = 0.0,
    late_payments_last_2_years: int = 0,
) -> None:
    conn = get_db()
    conn.execute(
        "INSERT INTO users (user_id, username, password, role, credit_score, gross_monthly_income, total_monthly_debt, late_payments_last_2_years) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, username, password, role, credit_score, gross_monthly_income, total_monthly_debt, late_payments_last_2_years),
    )
    conn.commit()
    conn.close()


def delete_user(user_id: str) -> None:
    conn = get_db()
    conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def delete_application(application_id: str) -> None:
    conn = get_db()
    conn.execute("DELETE FROM applications WHERE application_id = ?", (application_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# VULNERABLE: SQL injection via f-string (intentional for pen-testing lab)
# ---------------------------------------------------------------------------

def get_user_profile_raw(user_id: str) -> Dict[str, Any]:
    """Retrieve a user profile using an INTENTIONALLY vulnerable query.

    The user_id is interpolated directly into the SQL string, allowing
    SQL injection when crafted input is supplied.
    """
    query = f"SELECT * FROM users WHERE user_id = '{user_id}'"

    conn = get_db()
    try:
        rows = conn.execute(query).fetchall()
    except Exception as e:
        conn.close()
        return {"status": "error", "message": str(e), "query": query}

    conn.close()

    if len(rows) == 0:
        return {"status": "error", "message": f"User '{user_id}' not found.", "query": query}

    if len(rows) > 1:
        return {
            "status": "success",
            "query": query,
            "result": [_row_to_user_dict(r) for r in rows],
            "warning": "Multiple rows returned.",
        }

    return {"status": "success", "query": query, "result": _row_to_user_dict(rows[0])}


# ---------------------------------------------------------------------------
# Auto-initialise on import
# ---------------------------------------------------------------------------

init_db()
