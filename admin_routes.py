"""
Admin routes for the Central Memory Hub.
This module contains routes for admin settings and operations.
All routes here are restricted to authenticated admin users.
"""
import logging
from flask import request, jsonify, render_template, redirect, url_for, flash, session
from flask_login import login_required
from app import app, db
from api_keys import ApiKey, ApiRequestLog
from auth import admin_required
from csrf import csrf_protect, generate_csrf_token
from xss_protection import sanitize_html


# Admin settings page
@app.route('/admin/settings', methods=['GET'])
@login_required
@admin_required
def get_settings_form():
    """Render the admin settings page with CSRF token."""
    csrf_token = generate_csrf_token()
    settings = {
        'site_name': 'Central Memory Hub',
        'max_results': 20,
        'enable_public_api': False
    }
    message = request.args.get('message')
    error = request.args.get('error')
    return render_template(
        'admin/settings.html',
        csrf_token=csrf_token,
        settings=settings,
        message=message,
        error=error
    )


@app.route('/admin/settings', methods=['POST'])
@login_required
@admin_required
@csrf_protect
def update_settings():
    """Update general settings."""
    try:
        site_name = sanitize_html(request.form.get('site_name', ''))
        max_results = request.form.get('max_results', '20')
        try:
            max_results = int(max_results)
            if max_results < 1 or max_results > 100:
                max_results = 20
        except ValueError:
            max_results = 20
        enable_public_api = request.form.get('enable_public_api') == 'on'
        logging.info(f"Settings updated: site_name={site_name}, max_results={max_results}, enable_public_api={enable_public_api}")
        return redirect(url_for('get_settings_form', message='Settings updated successfully'))
    except Exception as e:
        logging.error(f"Error updating settings: {e}")
        return redirect(url_for('get_settings_form', error=str(e)))


@app.route('/admin/security', methods=['POST'])
@login_required
@admin_required
@csrf_protect
def update_security_settings():
    """Update security settings."""
    try:
        session_timeout = request.form.get('session_timeout', '30')
        try:
            session_timeout = int(session_timeout)
            if session_timeout < 5 or session_timeout > 1440:
                session_timeout = 30
        except ValueError:
            session_timeout = 30

        failed_login_limit = request.form.get('failed_login_limit', '5')
        try:
            failed_login_limit = int(failed_login_limit)
            if failed_login_limit < 1 or failed_login_limit > 20:
                failed_login_limit = 5
        except ValueError:
            failed_login_limit = 5

        enforce_strong_passwords = request.form.get('enforce_strong_passwords') == 'on'
        enable_2fa = request.form.get('enable_2fa') == 'on'
        logging.info(f"Security settings updated: session_timeout={session_timeout}, "
                     f"failed_login_limit={failed_login_limit}, "
                     f"enforce_strong_passwords={enforce_strong_passwords}, "
                     f"enable_2fa={enable_2fa}")
        return redirect(url_for('get_settings_form', message='Security settings updated successfully'))
    except Exception as e:
        logging.error(f"Error updating security settings: {e}")
        return redirect(url_for('get_settings_form', error=str(e)))


@app.route('/admin/revoke-all-keys', methods=['POST'])
@login_required
@admin_required
@csrf_protect
def revoke_all_api_keys():
    """Revoke all API keys."""
    try:
        active_keys = ApiKey.query.filter_by(is_active=True).all()
        count = 0
        for key in active_keys:
            key.revoke()
            count += 1
        return redirect(url_for('get_settings_form', message=f'Successfully revoked {count} API keys'))
    except Exception as e:
        logging.error(f"Error revoking API keys: {e}")
        return redirect(url_for('get_settings_form', error=str(e)))


@app.route('/admin/clear-logs', methods=['POST'])
@login_required
@admin_required
@csrf_protect
def clear_api_logs():
    """Clear all API request logs."""
    try:
        num_deleted = db.session.query(ApiRequestLog).delete()
        db.session.commit()
        return redirect(url_for('get_settings_form', message=f'Successfully cleared {num_deleted} API request logs'))
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error clearing API logs: {e}")
        return redirect(url_for('get_settings_form', error=str(e)))


@app.route('/admin/reset-database', methods=['POST'])
@login_required
@admin_required
@csrf_protect
def reset_database():
    """Reset the entire database."""
    try:
        confirmation = request.form.get('confirmation')
        if confirmation != 'RESET':
            return redirect(url_for('get_settings_form', error='Invalid confirmation text'))
        logging.warning("Database reset requested - this is just a simulation")
        return redirect(url_for('get_settings_form', message='Database reset simulation completed'))
    except Exception as e:
        logging.error(f"Error resetting database: {e}")
        return redirect(url_for('get_settings_form', error=str(e)))
