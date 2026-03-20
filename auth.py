"""
Authentication blueprint — login, logout, setup, user management,
user profiles, invitation flow, and organisation profile.
Decorators: login_required (any user), admin_required (admin only).
"""
import logging
import os
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, jsonify, abort, current_app
)
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename

from app import db
from models import User, InvitationToken, OrgProfile

auth_bp = Blueprint("auth", __name__)

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')


# ── Helpers ───────────────────────────────────────────────────────────────────

def _allowed_image(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def _save_upload(file_storage, subfolder: str = '') -> str | None:
    """Save an uploaded image; return the URL-safe relative path or None."""
    if not file_storage or file_storage.filename == '':
        return None
    if not _allowed_image(file_storage.filename):
        return None
    os.makedirs(os.path.join(UPLOAD_FOLDER, subfolder), exist_ok=True)
    filename = secure_filename(file_storage.filename)
    unique_name = f"{secrets.token_hex(8)}_{filename}"
    dest = os.path.join(UPLOAD_FOLDER, subfolder, unique_name)
    file_storage.save(dest)
    rel = f"uploads/{subfolder + '/' if subfolder else ''}{unique_name}"
    return rel


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
        return redirect(url_for("home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        user = User.query.filter_by(username=username).first()
        if user and user.is_active and user.check_password(password):
            login_user(user, remember=remember)
            next_page = request.args.get("next")
            return redirect(next_page or url_for("home"))

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
            return redirect(url_for("home"))

    return render_template("setup.html")


# ── User Profile ──────────────────────────────────────────────────────────────

@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        errors = []

        new_username = request.form.get("username", "").strip()
        new_email = request.form.get("email", "").strip()

        if not new_username:
            errors.append("Username is required.")
        if not new_email:
            errors.append("Email is required.")

        # Check uniqueness (exclude self)
        if new_username and new_username != current_user.username:
            if User.query.filter_by(username=new_username).first():
                errors.append("Username already taken.")
        if new_email and new_email != current_user.email:
            if User.query.filter_by(email=new_email).first():
                errors.append("Email already registered.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return redirect(url_for("auth.profile"))

        # Save profile image if provided
        img_file = request.files.get("profile_image")
        if img_file and img_file.filename:
            rel_path = _save_upload(img_file, subfolder='avatars')
            if rel_path:
                current_user.profile_image = rel_path
            else:
                flash("Invalid image format. Allowed: png, jpg, jpeg, gif, webp.", "warning")

        current_user.username = new_username
        current_user.email = new_email
        current_user.first_name = request.form.get("first_name", "").strip() or None
        current_user.last_name = request.form.get("last_name", "").strip() or None
        current_user.company_name = request.form.get("company_name", "").strip() or None
        current_user.phone = request.form.get("phone", "").strip() or None
        current_user.whatsapp = request.form.get("whatsapp", "").strip() or None
        current_user.signal = request.form.get("signal", "").strip() or None
        current_user.telegram = request.form.get("telegram", "").strip() or None
        current_user.website = request.form.get("website", "").strip() or None

        # Change password if provided
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        if new_password:
            if len(new_password) < 8:
                flash("New password must be at least 8 characters.", "danger")
                return redirect(url_for("auth.profile"))
            if new_password != confirm_password:
                flash("Passwords do not match.", "danger")
                return redirect(url_for("auth.profile"))
            current_user.set_password(new_password)

        db.session.commit()
        flash("Profile updated successfully.", "success")
        return redirect(url_for("auth.profile"))

    return render_template("profile.html")


# ── Invitation system (admin only) ───────────────────────────────────────────

@auth_bp.route("/users/invite", methods=["POST"])
@login_required
@admin_required
def invite_user():
    email_hint = request.form.get("email_hint", "").strip() or None
    token_str = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(hours=72)
    inv = InvitationToken(
        token=token_str,
        email_hint=email_hint,
        created_by=current_user.id,
        expires_at=expires,
    )
    db.session.add(inv)
    db.session.commit()
    invite_url = url_for("auth.register", token=token_str, _external=True)
    flash(f"Invitation link created (expires in 72 h):|{invite_url}", "invite")
    return redirect(url_for("auth.users"))


@auth_bp.route("/register/<token>", methods=["GET", "POST"])
def register(token):
    inv = InvitationToken.query.filter_by(token=token).first_or_404()

    if inv.is_expired:
        return render_template("register.html", error="This invitation link has expired.", inv=None)
    if inv.is_used:
        return render_template("register.html", error="This invitation link has already been used.", inv=None)

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
            return render_template("register.html", errors=errors, inv=inv,
                                   username=username, email=email)

        new_user = User(username=username, email=email, role="user")
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.flush()  # get the new_user.id

        inv.used_at = datetime.utcnow()
        inv.used_by = new_user.id
        db.session.commit()

        login_user(new_user)
        flash("Account created! Welcome to the Central Memory Hub.", "success")
        return redirect(url_for("home"))

    return render_template("register.html", inv=inv, errors=[], username="",
                           email=inv.email_hint or "")


# ── User management (admin only) ──────────────────────────────────────────────

@auth_bp.route("/users")
@login_required
@admin_required
def users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    pending_invites = (
        InvitationToken.query
        .filter(InvitationToken.used_at.is_(None))
        .filter(InvitationToken.expires_at > datetime.utcnow())
        .order_by(InvitationToken.created_at.desc())
        .all()
    )
    return render_template("users.html", users=all_users, pending_invites=pending_invites)


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
        username = user.username
        # Nullify FK references in invitation_tokens before deleting the user
        InvitationToken.query.filter_by(used_by=user_id).update({"used_by": None})
        db.session.delete(user)
        db.session.commit()
        flash(f"User '{username}' deleted.", "success")
    return redirect(url_for("auth.users"))


# ── Organisation Profile (admin only) ─────────────────────────────────────────

@auth_bp.route("/admin/org-profile", methods=["GET", "POST"])
@login_required
@admin_required
def org_profile():
    org = OrgProfile.query.get(1)
    if org is None:
        org = OrgProfile(id=1)
        db.session.add(org)
        db.session.commit()

    if request.method == "POST":
        logo_file = request.files.get("logo")
        if logo_file and logo_file.filename:
            rel_path = _save_upload(logo_file, subfolder='org')
            if rel_path:
                org.logo = rel_path
            else:
                flash("Invalid logo format. Allowed: png, jpg, jpeg, gif, webp.", "warning")

        org.org_name = request.form.get("org_name", "").strip() or None
        org.website = request.form.get("website", "").strip() or None
        org.contact_email = request.form.get("contact_email", "").strip() or None
        org.phone = request.form.get("phone", "").strip() or None
        org.description = request.form.get("description", "").strip() or None
        org.city = request.form.get("city", "").strip() or None
        org.state = request.form.get("state", "").strip() or None
        org.country = request.form.get("country", "").strip() or None
        org.linkedin = request.form.get("linkedin", "").strip() or None
        org.twitter = request.form.get("twitter", "").strip() or None
        org.facebook = request.form.get("facebook", "").strip() or None
        org.instagram = request.form.get("instagram", "").strip() or None

        db.session.commit()
        flash("Organisation profile updated.", "success")
        return redirect(url_for("auth.org_profile"))

    return render_template("admin/org_profile.html", org=org)
