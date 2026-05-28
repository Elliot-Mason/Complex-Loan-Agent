"""
Flask web server wrapping the LoanAgent.
"""

import logging
import os
import time
import uuid
from flask import Flask, g, jsonify, render_template, request, session

import database as db
from loan_agent import LoanAgent, calculate_risk_score, format_log_message, make_id

app = Flask(__name__)
app.secret_key = "super-secret-key-change-in-production"

AGENTS: dict = {}
API_LOGGER = logging.getLogger("complex_loan_agent.api")
SENSITIVE_LOG_FIELDS = {"password"}


def _sanitize_for_log(value):
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if key.lower() in SENSITIVE_LOG_FIELDS:
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = _sanitize_for_log(item)
        return sanitized

    if isinstance(value, list):
        return [_sanitize_for_log(item) for item in value]

    return value


def _log_api_event(event: str, **payload) -> None:
    API_LOGGER.info(format_log_message(event, **payload))


@app.before_request
def log_api_request():
    if not request.path.startswith("/api/"):
        return None

    g.request_started_at = time.perf_counter()
    _log_api_event(
        "api.request",
        method=request.method,
        path=request.path,
        query=request.args.to_dict(flat=False),
        body=_sanitize_for_log(request.get_json(silent=True)),
        user_id=session.get("user_id"),
    )
    return None


@app.after_request
def log_api_response(response):
    if not request.path.startswith("/api/"):
        return response

    started_at = getattr(g, "request_started_at", None)
    duration_ms = round((time.perf_counter() - started_at) * 1000, 2) if started_at is not None else None
    response_body = response.get_json(silent=True) if response.is_json else response.get_data(as_text=True)

    _log_api_event(
        "api.response",
        method=request.method,
        path=request.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
        body=_sanitize_for_log(response_body),
        user_id=session.get("user_id"),
    )
    return response


@app.errorhandler(Exception)
def handle_exception(e):
    API_LOGGER.exception(
        format_log_message(
            "api.exception",
            method=request.method,
            path=request.path,
            user_id=session.get("user_id"),
            error=str(e),
        )
    )
    return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", users=db.get_all_users())


@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(silent=True)
    if not data or "username" not in data or "password" not in data:
        return jsonify({"error": "Missing 'username' or 'password'."}), 400

    username = data["username"].strip()
    password = data["password"].strip()

    if not username or not password:
        return jsonify({"error": "Username and password are required."}), 400

    for u in db.get_all_users().values():
        if u["username"].lower() == username.lower():
            return jsonify({"error": "Username already exists."}), 409

    user_id = make_id("usr")
    db.insert_user(user_id=user_id, username=username, password=password, role="Applier")
    user = db.get_user(user_id)
    return jsonify({"status": "success", "user": user}), 201


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True)
    if not data or "username" not in data or "password" not in data:
        return jsonify({"error": "Missing 'username' or 'password'."}), 400

    username = data["username"].strip()
    password = data["password"]

    # Look up user by username
    users_db = db.get_all_users()
    user_id = None
    for uid, u in users_db.items():
        if u["username"].lower() == username.lower():
            user_id = uid
            break

    if not user_id:
        return jsonify({"error": "Invalid username or password."}), 401

    user = users_db[user_id]
    if user["password"] != password:
        return jsonify({"error": "Invalid username or password."}), 401

    sid = str(uuid.uuid4())
    session["sid"] = sid
    session["user_id"] = user_id

    # Only create an agent for non-Admin users
    if user["role"] != "Admin":
        try:
            AGENTS[sid] = LoanAgent(current_user_id=user_id)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({
        "status": "success",
        "user": {
            "user_id": user["user_id"],
            "username": user["username"],
            "role": user["role"],
            "profile": user["profile"],
        },
    })


@app.route("/api/logout", methods=["POST"])
def logout():
    sid = session.get("sid")
    if sid and sid in AGENTS:
        del AGENTS[sid]
    session.clear()
    return jsonify({"status": "success", "message": "Logged out."})


@app.route("/api/chat", methods=["POST"])
def chat():
    sid = session.get("sid")
    if not sid or sid not in AGENTS:
        return jsonify({"error": "Not logged in."}), 401

    data = request.get_json(silent=True)
    if not data or "message" not in data:
        return jsonify({"error": "Missing 'message' in request body."}), 400

    agent = AGENTS[sid]
    try:
        response_text = agent.chat(data["message"])
    except Exception as e:
        return jsonify({"error": f"Agent error: {e}"}), 500

    return jsonify({"response": response_text})


@app.route("/api/user", methods=["GET"])
def get_user():
    user_id = session.get("user_id")
    user = db.get_user(user_id) if user_id else None
    if not user:
        return jsonify({"error": "Not logged in."}), 401
    return jsonify({
        "user_id": user["user_id"],
        "username": user["username"],
        "role": user["role"],
        "profile": user["profile"],
    })


@app.route("/api/applications", methods=["GET"])
def get_applications():
    user_id = session.get("user_id")
    user = db.get_user(user_id) if user_id else None
    if not user:
        return jsonify({"error": "Not logged in."}), 401

    all_apps = db.get_all_applications()
    if user["role"] == "Approver":
        apps = list(all_apps.values())
    else:
        apps = [a for a in all_apps.values() if a["user_id"] == user_id]

    return jsonify({"applications": apps})


@app.route("/api/pending-reviews", methods=["GET"])
def pending_reviews():
    user_id = session.get("user_id")
    user = db.get_user(user_id) if user_id else None
    if not user or user["role"] != "Approver":
        return jsonify({"error": "Approver access required."}), 403

    all_apps = db.get_all_applications()
    all_users = db.get_all_users()

    grouped = {}
    for a in all_apps.values():
        if a["status"] != "Pending":
            continue
        uid = a["user_id"]
        if uid not in grouped:
            u = all_users.get(uid, {})
            grouped[uid] = {
                "user_id": uid,
                "username": u.get("username", uid),
                "applications": [],
            }
        grouped[uid]["applications"].append(a)

    return jsonify({"appliers": list(grouped.values())})


# ---------------------------------------------------------------------------
# Admin API routes
# ---------------------------------------------------------------------------

def _require_admin():
    """Return user_id if admin, else None and a JSON error tuple."""
    user_id = session.get("user_id")
    user = db.get_user(user_id) if user_id else None
    if not user:
        return None, (jsonify({"error": "Not logged in."}), 401)
    if user["role"] != "Admin":
        return None, (jsonify({"error": "Admin access required."}), 403)
    return user_id, None


@app.route("/api/admin/users", methods=["GET"])
def admin_get_users():
    _, err = _require_admin()
    if err:
        return err
    users = []
    for u in db.get_all_users().values():
        users.append({
            "user_id": u["user_id"],
            "username": u["username"],
            "password": u["password"],
            "role": u["role"],
            "profile": u["profile"],
        })
    return jsonify({"users": users})


@app.route("/api/admin/users/<user_id>", methods=["PUT"])
def admin_update_user(user_id):
    _, err = _require_admin()
    if err:
        return err
    user = db.get_user(user_id)
    if not user:
        return jsonify({"error": f"User '{user_id}' not found."}), 404

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No data provided."}), 400

    updates = {}
    if "username" in data:
        updates["username"] = data["username"]
    if "password" in data:
        updates["password"] = data["password"]
    if "role" in data and data["role"] in ("Applier", "Approver", "Admin"):
        updates["role"] = data["role"]
    if "profile" in data and isinstance(data["profile"], dict):
        for key in ("credit_score", "gross_monthly_income", "total_monthly_debt", "late_payments_last_2_years"):
            if key in data["profile"]:
                if key in ("credit_score", "late_payments_last_2_years"):
                    updates[key] = int(data["profile"][key])
                else:
                    updates[key] = float(data["profile"][key])

    if updates:
        db.update_user(user_id, **updates)

    user = db.get_user(user_id)
    return jsonify({"status": "success", "user": user})


@app.route("/api/admin/users", methods=["POST"])
def admin_create_user():
    _, err = _require_admin()
    if err:
        return err

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No data provided."}), 400

    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    role = data.get("role", "Applier")

    if not username or not password:
        return jsonify({"error": "Username and password are required."}), 400
    if role not in ("Applier", "Approver", "Admin"):
        return jsonify({"error": "Invalid role."}), 400

    # Check for duplicate username
    for u in db.get_all_users().values():
        if u["username"].lower() == username.lower():
            return jsonify({"error": "Username already exists."}), 409

    user_id = make_id("usr")

    profile = data.get("profile", {})
    db.insert_user(
        user_id=user_id,
        username=username,
        password=password,
        role=role,
        credit_score=int(profile.get("credit_score", 0)),
        gross_monthly_income=float(profile.get("gross_monthly_income", 0.0)),
        total_monthly_debt=float(profile.get("total_monthly_debt", 0.0)),
        late_payments_last_2_years=int(profile.get("late_payments_last_2_years", 0)),
    )

    user = db.get_user(user_id)
    return jsonify({"status": "success", "user": user}), 201


@app.route("/api/admin/users/<user_id>", methods=["DELETE"])
def admin_delete_user(user_id):
    _, err = _require_admin()
    if err:
        return err

    user = db.get_user(user_id)
    if not user:
        return jsonify({"error": f"User '{user_id}' not found."}), 404

    # Prevent deleting yourself
    if user_id == session.get("user_id"):
        return jsonify({"error": "Cannot delete your own account."}), 400

    db.delete_user(user_id)
    return jsonify({"status": "success", "message": f"User '{user_id}' deleted."})


@app.route("/api/admin/applications", methods=["GET"])
def admin_get_applications():
    _, err = _require_admin()
    if err:
        return err
    all_apps = db.get_all_applications()
    # Optional filter by user_id
    filter_user = request.args.get("user_id")
    if filter_user:
        apps = [a for a in all_apps.values() if a["user_id"] == filter_user]
    else:
        apps = list(all_apps.values())
    return jsonify({"applications": apps})


@app.route("/api/admin/applications/<application_id>", methods=["PUT"])
def admin_update_application(application_id):
    _, err = _require_admin()
    if err:
        return err
    app_obj = db.get_application(application_id)
    if not app_obj:
        return jsonify({"error": f"Application '{application_id}' not found."}), 404

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No data provided."}), 400

    updates = {}
    if "status" in data and data["status"] in ("Pending", "Approved", "Denied"):
        updates["status"] = data["status"]
    if "loan_amount" in data:
        updates["loan_amount"] = float(data["loan_amount"])
    if "duration_months" in data:
        updates["duration_months"] = int(data["duration_months"])
    if "metadata" in data and isinstance(data["metadata"], dict):
        for k, v in data["metadata"].items():
            updates[k] = v

    if updates:
        db.update_application(application_id, **updates)

    app_obj = db.get_application(application_id)
    return jsonify({"status": "success", "application": app_obj})


@app.route("/api/admin/applications/<application_id>", methods=["DELETE"])
def admin_delete_application(application_id):
    _, err = _require_admin()
    if err:
        return err

    app_obj = db.get_application(application_id)
    if not app_obj:
        return jsonify({"error": f"Application '{application_id}' not found."}), 404

    db.delete_application(application_id)
    return jsonify({"status": "success", "message": f"Application '{application_id}' deleted."})


@app.route("/api/admin/reset", methods=["POST"])
def admin_reset_database():
    _, err = _require_admin()
    if err:
        return err

    db.reset_db()
    AGENTS.clear()
    return jsonify({"status": "success", "message": "Database reset to the original seed data."})


@app.route("/api/redteam", methods=["POST"])
def redteam_chat():
    """
    An API-protected endpoint for automated red-teaming (e.g., Lakera Red).
    Authenticates using 'X-Username' and 'X-Password' headers.
    Bypasses session cookies for easier automation.
    """
    username = request.headers.get("X-Username")
    password = request.headers.get("X-Password")

    if not username or not password:
        return jsonify({"error": "Missing 'X-Username' or 'X-Password' headers."}), 401

    # Look up user by username
    users_db = db.get_all_users()
    user_id = None
    for uid, u in users_db.items():
        if u["username"].lower() == username.lower():
            user_id = uid
            break

    if not user_id or users_db[user_id]["password"] != password:
        return jsonify({"error": "Invalid username or password."}), 401

    user = users_db[user_id]
    if user["role"] == "Admin":
        return jsonify({"error": "Red-teaming is only allowed for Appliers and Approvers."}), 403

    data = request.get_json(silent=True)
    if not data or "message" not in data:
        return jsonify({"error": "Missing 'message' in request body."}), 400

    try:
        # Create a transient agent for this specific user
        agent = LoanAgent(current_user_id=user_id)
        response_text = agent.chat(data["message"])
        
        # Return an OpenAI-compatible response format
        return jsonify({
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": response_text
                    },
                    "finish_reason": "stop",
                    "index": 0
                }
            ],
            "model": agent.model,
            "object": "chat.completion"
        })
    except Exception as e:
        return jsonify({"error": f"Agent error: {e}"}), 500


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, port=8080)
