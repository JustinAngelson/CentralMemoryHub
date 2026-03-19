"""
Authentication blueprint — login, logout, setup, user management.
Decorators: login_required (any user), admin_required (admin only).
"""
import logging
from functools import wraps

from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, jsonify, abort
)
from flask_login import login_user, logout_user, login_required, current_user

from app import db
from models import User

auth_bp = Blueprint("auth", __name__)


# ── Decorators ────────────────────────────────────────────────────────────────

def admin_required(f):
    """Restrict a view to admin users only. Must be used after @login_required."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.url))
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ── Auth routes ───────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        user = User.query.filter_by(username=username).first()
        if user and user.is_active and user.check_password(password):
            login_user(user, remember=remember)
            next_page = request.args.get("next")
            return redirect(next_page or url_for("index"))

        flash("Invalid username or password.", "danger")

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


# ── First-run setup (disabled once any admin exists) ─────────────────────────

@auth_bp.route("/setup", methods=["GET", "POST"])
def setup():
    if User.query.filter_by(role="admin").first():
        flash("Setup is already complete. Please log in.", "info")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        errors = []
        if not username:
            errors.append("Username is required.")
        if not email:
            errors.append("Email is required.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if User.query.filter_by(username=username).first():
            errors.append("Username already taken.")
        if User.query.filter_by(email=email).first():
            errors.append("Email already registered.")

        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            admin = User(username=username, email=email, role="admin")
            admin.set_password(password)
            db.session.add(admin)
            db.session.commit()
            login_user(admin)
            flash(f"Admin account '{username}' created. Welcome!", "success")
            return redirect(url_for("index"))

    return render_template("setup.html")


# ── User management (admin only) ──────────────────────────────────────────────

@auth_bp.route("/users")
@login_required
@admin_required
def users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template("users.html", users=all_users)


@auth_bp.route("/users/create", methods=["POST"])
@login_required
@admin_required
def create_user():
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    role = request.form.get("role", "user")

    errors = []
    if not username:
        errors.append("Username is required.")
    if not email:
        errors.append("Email is required.")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if role not in ("admin", "user"):
        errors.append("Invalid role.")
    if User.query.filter_by(username=username).first():
        errors.append("Username already taken.")
    if User.query.filter_by(email=email).first():
        errors.append("Email already registered.")

    if errors:
        for e in errors:
            flash(e, "danger")
    else:
        new_user = User(username=username, email=email, role=role)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        flash(f"User '{username}' created successfully.", "success")

    return redirect(url_for("auth.users"))


@auth_bp.route("/users/<user_id>/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("You cannot deactivate your own account.", "danger")
    else:
        user.is_active = not user.is_active
        db.session.commit()
        state = "activated" if user.is_active else "deactivated"
        flash(f"User '{user.username}' {state}.", "success")
    return redirect(url_for("auth.users"))


@auth_bp.route("/users/<user_id>/role", methods=["POST"])
@login_required
@admin_required
def change_role(user_id):
    user = User.query.get_or_404(user_id)
    new_role = request.form.get("role")
    if new_role not in ("admin", "user"):
        flash("Invalid role.", "danger")
    elif user.id == current_user.id:
        flash("You cannot change your own role.", "danger")
    else:
        user.role = new_role
        db.session.commit()
        flash(f"'{user.username}' is now {new_role}.", "success")
    return redirect(url_for("auth.users"))


@auth_bp.route("/users/<user_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("You cannot delete your own account.", "danger")
    else:
        db.session.delete(user)
        db.session.commit()
        flash(f"User '{user.username}' deleted.", "success")
    return redirect(url_for("auth.users"))
