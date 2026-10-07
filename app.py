import os
import re
import sqlite3
from datetime import date, datetime
from functools import wraps

from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "database.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-this-secret-key-before-deploying"

STATUSES = ("Pending", "In Progress", "Completed")
PRIORITIES = ("Low", "Medium", "High")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------- Database helpers ----------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Pending',
            priority TEXT NOT NULL DEFAULT 'Medium',
            due_date TEXT NOT NULL,
            category TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        );
        """
    )
    db.commit()
    db.close()


# ---------- Auth helpers ----------
def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper


def api_login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify(error="Please log in to continue."), 401
        return view(*args, **kwargs)
    return wrapper


# ---------- Page routes ----------
@app.route("/")
def index():
    return redirect(url_for("dashboard" if "user_id" in session else "login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    error = None
    if not name or not email or not password:
        error = "All fields are required."
    elif len(name) > 80:
        error = "Name must be 80 characters or fewer."
    elif not EMAIL_RE.match(email):
        error = "Please enter a valid email address."
    elif len(password) < 6:
        error = "Password must be at least 6 characters."
    if not error:
        db = get_db()
        if db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
            error = "An account with this email already exists."
        else:
            db.execute(
                "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
                (name, email, generate_password_hash(password)),
            )
            db.commit()
            return render_template("login.html", success="Account created. Please log in.")
    return render_template("register.html", error=error, name=name, email=email)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if "user_id" in session:
            return redirect(url_for("dashboard"))
        return render_template("login.html")
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if user is None or not check_password_hash(user["password"], password):
        return render_template("login.html", error="Invalid email or password.", email=email)
    session.clear()
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", name=session["user_name"])


# ---------- API helpers ----------
def task_to_dict(row):
    today = date.today().isoformat()
    d = dict(row)
    d["overdue"] = d["status"] != "Completed" and d["due_date"] < today
    return d


def validate_task(data):
    """Return (clean_data, error_message)."""
    if not isinstance(data, dict):
        return None, "Invalid request data."
    title = str(data.get("title", "")).strip()
    description = str(data.get("description", "") or "").strip()
    category = str(data.get("category", "") or "").strip()
    status = data.get("status", "Pending")
    priority = data.get("priority", "Medium")
    due = str(data.get("due_date", "") or "").strip()
    if not title:
        return None, "Task title cannot be empty."
    if len(title) > 100:
        return None, "Title must be 100 characters or fewer."
    if len(description) > 1000:
        return None, "Description must be 1000 characters or fewer."
    if len(category) > 40:
        return None, "Category must be 40 characters or fewer."
    if status not in STATUSES:
        return None, "Invalid status."
    if priority not in PRIORITIES:
        return None, "Invalid priority."
    try:
        datetime.strptime(due, "%Y-%m-%d")
    except ValueError:
        return None, "Please enter a valid due date."
    return dict(title=title, description=description, category=category,
                status=status, priority=priority, due_date=due), None


def get_own_task(task_id):
    return get_db().execute(
        "SELECT * FROM tasks WHERE id = ? AND user_id = ?", (task_id, session["user_id"])
    ).fetchone()


# ---------- API routes ----------
@app.route("/api/tasks", methods=["GET"])
@api_login_required
def list_tasks():
    sql = "SELECT * FROM tasks WHERE user_id = ?"
    params = [session["user_id"]]
    q = request.args.get("q", "").strip()
    if q:
        sql += " AND title LIKE ?"
        params.append(f"%{q}%")
    for field in ("status", "priority", "category"):
        value = request.args.get(field, "").strip()
        if value:
            sql += f" AND {field} = ?"
            params.append(value)
    order = "DESC" if request.args.get("sort") == "desc" else "ASC"
    sql += f" ORDER BY due_date {order}, id DESC"
    rows = get_db().execute(sql, params).fetchall()
    return jsonify([task_to_dict(r) for r in rows])


@app.route("/api/stats", methods=["GET"])
@api_login_required
def stats():
    db = get_db()
    uid = session["user_id"]
    rows = db.execute("SELECT status, due_date FROM tasks WHERE user_id = ?", (uid,)).fetchall()
    today = date.today().isoformat()
    cats = db.execute(
        "SELECT DISTINCT category FROM tasks WHERE user_id = ? AND category != '' ORDER BY category",
        (uid,),
    ).fetchall()
    return jsonify(
        total=len(rows),
        pending=sum(r["status"] == "Pending" for r in rows),
        in_progress=sum(r["status"] == "In Progress" for r in rows),
        completed=sum(r["status"] == "Completed" for r in rows),
        overdue=sum(r["status"] != "Completed" and r["due_date"] < today for r in rows),
        categories=[c["category"] for c in cats],
    )


@app.route("/api/tasks", methods=["POST"])
@api_login_required
def create_task():
    clean, error = validate_task(request.get_json(silent=True))
    if error:
        return jsonify(error=error), 400
    db = get_db()
    cur = db.execute(
        "INSERT INTO tasks (user_id, title, description, status, priority, due_date, category) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session["user_id"], clean["title"], clean["description"], clean["status"],
         clean["priority"], clean["due_date"], clean["category"]),
    )
    db.commit()
    return jsonify(task_to_dict(get_own_task(cur.lastrowid))), 201


@app.route("/api/tasks/<int:task_id>", methods=["PUT"])
@api_login_required
def update_task(task_id):
    if get_own_task(task_id) is None:
        return jsonify(error="Task not found."), 404
    clean, error = validate_task(request.get_json(silent=True))
    if error:
        return jsonify(error=error), 400
    db = get_db()
    db.execute(
        "UPDATE tasks SET title = ?, description = ?, status = ?, priority = ?, due_date = ?, "
        "category = ? WHERE id = ? AND user_id = ?",
        (clean["title"], clean["description"], clean["status"], clean["priority"],
         clean["due_date"], clean["category"], task_id, session["user_id"]),
    )
    db.commit()
    return jsonify(task_to_dict(get_own_task(task_id)))


@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
@api_login_required
def delete_task(task_id):
    if get_own_task(task_id) is None:
        return jsonify(error="Task not found."), 404
    db = get_db()
    db.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, session["user_id"]))
    db.commit()
    return jsonify(message="Task deleted.")


@app.route("/api/tasks/<int:task_id>/complete", methods=["PATCH"])
@api_login_required
def complete_task(task_id):
    if get_own_task(task_id) is None:
        return jsonify(error="Task not found."), 404
    db = get_db()
    db.execute("UPDATE tasks SET status = 'Completed' WHERE id = ? AND user_id = ?",
               (task_id, session["user_id"]))
    db.commit()
    return jsonify(task_to_dict(get_own_task(task_id)))


init_db()  # creates database.db and tables automatically

if __name__ == "__main__":
    app.run(debug=True)
