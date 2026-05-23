"""
Authentication routes: login, logout, register, password management.
"""

from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from flask_jwt_extended import create_access_token, create_refresh_token, jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash

from src.database import db
from src.database.models import User, Role, AuditLog


auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


# ============================================================
# WEB ROUTES (HTML pages)
# ============================================================

@auth_bp.route('/login', methods=['GET'])
def login():
    """Render login page."""
    if current_user.is_authenticated:
        # main_dashboard is the route function name registered in main.py
        return redirect(url_for('main_dashboard'))
    return render_template('auth/login.html')


@auth_bp.route('/register', methods=['GET'])
def register():
    """Render registration page."""
    if current_user.is_authenticated:
        return redirect(url_for('main_dashboard'))
    return render_template('auth/register.html')


@auth_bp.route('/logout', methods=['GET'])
@login_required
def logout():
    """Logout user."""
    username = current_user.username
    
    # Log the action
    log_audit(
        user_id=current_user.id,
        username=username,
        action='logout',
        resource='auth',
        status='success'
    )
    
    logout_user()
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('auth.login'))


# ============================================================
# API ROUTES (JSON endpoints)
# ============================================================

@auth_bp.route('/api/login', methods=['POST'])
def api_login():
    """
    API login endpoint.
    
    Request body:
    {
        "username": "admin",
        "password": "password123",
        "remember": false
    }
    """
    data = request.get_json()
    
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({'error': 'Username and password required'}), 400
    
    username = data['username'].strip()
    password = data['password']
    
    user = User.query.filter_by(username=username).first()
    
    # Check if user exists
    if not user:
        log_audit(
            username=username,
            action='login_failed',
            resource='auth',
            status='failure',
            details={'reason': 'user_not_found'}
        )
        return jsonify({'error': 'Invalid username or password'}), 401
    
    # Check if account is locked
    if user.locked_until and user.locked_until > datetime.utcnow():
        return jsonify({
            'error': 'Account is temporarily locked',
            'locked_until': user.locked_until.isoformat()
        }), 403
    
    # Check if account is active
    if not user.is_active:
        return jsonify({'error': 'Account is disabled'}), 403
    
    # Verify password
    if not user.check_password(password):
        # Increment failed attempts
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= 5:
            user.locked_until = datetime.utcnow() + timedelta(minutes=15)
        db.session.commit()
        
        log_audit(
            user_id=user.id,
            username=username,
            action='login_failed',
            resource='auth',
            status='failure',
            details={'reason': 'invalid_password', 'attempts': user.failed_login_attempts}
        )
        return jsonify({'error': 'Invalid username or password'}), 401
    
    # Reset failed attempts on successful login
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login = datetime.utcnow()
    db.session.commit()
    
    # Log in user
    remember = data.get('remember', False)
    login_user(user, remember=remember)
    
    # Create JWT tokens
    access_token = create_access_token(identity=user.id, fresh=True)
    refresh_token = create_refresh_token(identity=user.id)
    
    log_audit(
        user_id=user.id,
        username=user.username,
        action='login_success',
        resource='auth',
        status='success'
    )
    
    return jsonify({
        'success': True,
        'message': 'Login successful',
        'user': user.to_dict(),
        'access_token': access_token,
        'refresh_token': refresh_token
    }), 200


@auth_bp.route('/api/register', methods=['POST'])
def api_register():
    """
    API registration endpoint.
    
    Request body:
    {
        "username": "johndoe",
        "email": "john@example.com",
        "password": "SecurePass123!",
        "full_name": "John Doe"
    }
    """
    data = request.get_json()
    
    # Validate required fields
    required = ['username', 'email', 'password']
    if not all(field in data for field in required):
        return jsonify({'error': 'Missing required fields'}), 400
    
    username = data['username'].strip()
    email = data['email'].strip().lower()
    password = data['password']
    
    # Validate username
    if len(username) < 3 or len(username) > 50:
        return jsonify({'error': 'Username must be 3-50 characters'}), 400
    
    # Validate password strength
    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400
    
    # Check if user exists
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already taken'}), 409
    
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email already registered'}), 409
    
    # Get default viewer role
    viewer_role = Role.query.filter_by(name='viewer').first()
    if not viewer_role:
        return jsonify({'error': 'System configuration error'}), 500
    
    # Create new user
    user = User(
        username=username,
        email=email,
        full_name=data.get('full_name'),
        role_id=viewer_role.id,
        is_active=True,
        is_verified=False
    )
    user.set_password(password)
    
    db.session.add(user)
    db.session.commit()
    
    # Issue a starter checking account + debit card so the user can
    # start transacting immediately.
    try:
        from src.banking import seed_user_banking
        seed_user_banking(user)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # Don't fail registration if banking seed fails — the user can
        # be re-seeded on first banking-page visit.
        print(f"Banking seed failed for {user.username}: {e}")
    
    log_audit(
        user_id=user.id,
        username=user.username,
        action='user_registered',
        resource='auth',
        status='success'
    )
    
    return jsonify({
        'success': True,
        'message': 'Registration successful',
        'user': user.to_dict()
    }), 201


@auth_bp.route('/api/refresh', methods=['POST'])
@jwt_required(refresh=True)
def api_refresh():
    """Refresh access token using refresh token."""
    identity = get_jwt_identity()
    access_token = create_access_token(identity=identity, fresh=False)
    
    return jsonify({
        'success': True,
        'access_token': access_token
    }), 200


@auth_bp.route('/api/me', methods=['GET'])
@login_required
def api_me():
    """Get current user info."""
    return jsonify({
        'success': True,
        'user': current_user.to_dict(include_sensitive=True)
    }), 200


@auth_bp.route('/api/change-password', methods=['POST'])
@login_required
def api_change_password():
    """
    Change user password.
    
    Request body:
    {
        "current_password": "OldPass123",
        "new_password": "NewPass456"
    }
    """
    data = request.get_json()
    
    if not data or not data.get('current_password') or not data.get('new_password'):
        return jsonify({'error': 'Current and new password required'}), 400
    
    # Verify current password
    if not current_user.check_password(data['current_password']):
        log_audit(
            user_id=current_user.id,
            username=current_user.username,
            action='password_change_failed',
            resource='auth',
            status='failure',
            details={'reason': 'invalid_current_password'}
        )
        return jsonify({'error': 'Current password is incorrect'}), 401
    
    # Validate new password
    new_password = data['new_password']
    if len(new_password) < 8:
        return jsonify({'error': 'New password must be at least 8 characters'}), 400
    
    # Update password
    current_user.set_password(new_password)
    current_user.updated_at = datetime.utcnow()
    db.session.commit()
    
    log_audit(
        user_id=current_user.id,
        username=current_user.username,
        action='password_changed',
        resource='auth',
        status='success'
    )
    
    return jsonify({
        'success': True,
        'message': 'Password changed successfully'
    }), 200


# ============================================================
# PROFILE MANAGEMENT
# ============================================================

@auth_bp.route('/profile', methods=['GET'])
@login_required
def profile_page():
    """Render user profile page."""
    return render_template('auth/profile.html')


@auth_bp.route('/api/profile', methods=['PUT'])
@login_required
def api_update_profile():
    """
    Update user profile (non-sensitive fields).
    
    Request body:
    {
        "full_name": "John Doe",
        "phone": "+1-555-0100",
        "department": "Risk",
        "country": "US",
        "preferred_currency": "USD",
        "job_title": "Fraud Analyst",
        "bio": "...",
        "notify_email": true,
        "notify_high_risk": true,
        "notify_critical_only": false
    }
    """
    data = request.get_json() or {}
    
    # Whitelist editable fields (security: never let users change role/is_active here)
    editable_fields = [
        'full_name', 'phone', 'department', 'country', 'preferred_currency',
        'job_title', 'bio', 'avatar_url',
        'notify_email', 'notify_high_risk', 'notify_critical_only',
    ]
    
    updated = []
    for field in editable_fields:
        if field in data:
            setattr(current_user, field, data[field])
            updated.append(field)
    
    # Special validation for email (still allow if explicitly provided)
    if 'email' in data and data['email'] != current_user.email:
        new_email = data['email'].strip().lower()
        existing = User.query.filter(User.email == new_email, User.id != current_user.id).first()
        if existing:
            return jsonify({'error': 'Email already in use'}), 409
        current_user.email = new_email
        current_user.is_verified = False  # require re-verification
        updated.append('email')
    
    current_user.updated_at = datetime.utcnow()
    db.session.commit()
    
    log_audit(
        user_id=current_user.id,
        username=current_user.username,
        action='profile_updated',
        resource='user',
        resource_id=str(current_user.id),
        status='success',
        details={'fields': updated}
    )
    
    return jsonify({
        'success': True,
        'message': 'Profile updated successfully',
        'user': current_user.to_dict(include_sensitive=True),
    }), 200


@auth_bp.route('/api/security-question', methods=['POST'])
@login_required
def api_set_security_question():
    """
    Set or update security question and answer.
    
    Request body:
    {
        "question": "What was the name of your first pet?",
        "answer": "Fluffy",
        "current_password": "MyPass123"
    }
    """
    data = request.get_json() or {}
    
    question = (data.get('question') or '').strip()
    answer = (data.get('answer') or '').strip()
    current_password = data.get('current_password', '')
    
    if not question or not answer or not current_password:
        return jsonify({'error': 'Question, answer, and current password required'}), 400
    
    if len(answer) < 2:
        return jsonify({'error': 'Answer must be at least 2 characters'}), 400
    
    # Verify password before allowing security change
    if not current_user.check_password(current_password):
        return jsonify({'error': 'Current password is incorrect'}), 401
    
    current_user.security_question = question
    current_user.set_security_answer(answer)
    current_user.updated_at = datetime.utcnow()
    db.session.commit()
    
    log_audit(
        user_id=current_user.id,
        username=current_user.username,
        action='security_question_set',
        resource='auth',
        status='success'
    )
    
    return jsonify({
        'success': True,
        'message': 'Security question saved successfully'
    }), 200


@auth_bp.route('/api/forgot-password', methods=['POST'])
def api_forgot_password():
    """
    Initiate password recovery using security question.
    
    Step 1: POST { "username": "john" } -> returns { "question": "..." }
    Step 2: POST { "username": "john", "answer": "...", "new_password": "..." } -> resets
    """
    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    
    if not username:
        return jsonify({'error': 'Username required'}), 400
    
    user = User.query.filter(
        (User.username == username) | (User.email == username.lower())
    ).first()
    
    # Don't reveal whether user exists
    if not user or not user.security_question:
        # Generic response to avoid enumeration
        return jsonify({
            'error': 'No security question configured for this account. Contact your administrator.'
        }), 404
    
    answer = data.get('answer')
    new_password = data.get('new_password')
    
    # Step 1: just return the question
    if not answer:
        return jsonify({
            'success': True,
            'security_question': user.security_question
        }), 200
    
    # Step 2: verify answer and reset password
    if not user.check_security_answer(answer):
        log_audit(
            user_id=user.id,
            username=user.username,
            action='password_reset_failed',
            resource='auth',
            status='failure',
            details={'reason': 'wrong_security_answer'}
        )
        return jsonify({'error': 'Incorrect answer'}), 401
    
    if not new_password or len(new_password) < 8:
        return jsonify({'error': 'New password must be at least 8 characters'}), 400
    
    user.set_password(new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    user.updated_at = datetime.utcnow()
    db.session.commit()
    
    log_audit(
        user_id=user.id,
        username=user.username,
        action='password_reset_via_security_question',
        resource='auth',
        status='success'
    )
    
    return jsonify({
        'success': True,
        'message': 'Password reset successfully. You can now log in with your new password.'
    }), 200


# ============================================================
# FACE AUTHENTICATION
# ============================================================
# Uses face-api.js client-side to compute a 128-dim descriptor.
# We compare the descriptors server-side via Euclidean distance.
# 0.6 is face-api.js's recommended default and balances false rejections
# vs. false matches. Override via the FACE_MATCH_THRESHOLD env var if you
# want it tighter (e.g. 0.5) or looser (e.g. 0.65).
import math
import os as _os
FACE_MATCH_THRESHOLD = float(_os.environ.get('FACE_MATCH_THRESHOLD', '0.6'))


def _euclidean_distance(a, b) -> float:
    """Euclidean distance between two equal-length numeric sequences."""
    if not a or not b or len(a) != len(b):
        return float('inf')
    s = 0.0
    for x, y in zip(a, b):
        d = float(x) - float(y)
        s += d * d
    return s ** 0.5


def _validate_descriptor(desc) -> bool:
    """Sanity-check a face descriptor: list of 128 finite numbers."""
    if not isinstance(desc, list):
        return False
    if len(desc) != 128:
        return False
    try:
        return all(math.isfinite(float(x)) for x in desc)
    except (TypeError, ValueError):
        return False


@auth_bp.route('/api/face/enroll', methods=['POST'])
@login_required
def api_face_enroll():
    """
    Enroll (or re-enroll) the current user's face.

    Request body:
    {
        "descriptor": [0.123, -0.456, ...]   // 128 floats from face-api.js
    }
    """
    data = request.get_json() or {}
    descriptor = data.get('descriptor')

    if not _validate_descriptor(descriptor):
        return jsonify({'error': 'Invalid face descriptor (expected 128 numbers)'}), 400

    current_user.face_descriptor = list(map(float, descriptor))
    current_user.face_enabled = True
    current_user.face_enrolled_at = datetime.utcnow()
    current_user.updated_at = datetime.utcnow()
    db.session.commit()

    log_audit(
        user_id=current_user.id,
        username=current_user.username,
        action='face_enrolled',
        resource='auth',
        status='success',
    )

    return jsonify({
        'success': True,
        'message': 'Face authentication enrolled',
        'enrolled_at': current_user.face_enrolled_at.isoformat(),
    }), 200


@auth_bp.route('/api/face/disable', methods=['POST'])
@login_required
def api_face_disable():
    """Disable face authentication for the current user."""
    current_user.face_enabled = False
    current_user.face_descriptor = None
    current_user.face_enrolled_at = None
    current_user.updated_at = datetime.utcnow()
    db.session.commit()

    log_audit(
        user_id=current_user.id,
        username=current_user.username,
        action='face_disabled',
        resource='auth',
        status='success',
    )

    return jsonify({'success': True, 'message': 'Face authentication disabled'}), 200


@auth_bp.route('/api/face/login', methods=['POST'])
def api_face_login():
    """
    Login using face descriptor instead of password.

    Request body:
    {
        "username": "admin",
        "descriptor": [0.123, -0.456, ...],
        "final":      false   // optional, default false
    }

    The face login UI captures multiple frames in a row and POSTs each one
    as a candidate. To avoid locking accounts after a few imperfect frames
    in a single legitimate session, we only count a *failed login attempt*
    (toward the 5-strike, 15-minute lockout) when the client signals
    ``final: true`` on its very last retry. Non-final misses return 401
    but do NOT touch ``failed_login_attempts``.
    """
    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    descriptor = data.get('descriptor')
    is_final = bool(data.get('final', False))

    if not username:
        return jsonify({'error': 'Username required'}), 400
    if not _validate_descriptor(descriptor):
        return jsonify({'error': 'Invalid face descriptor'}), 400

    user = User.query.filter(
        (User.username == username) | (User.email == username.lower())
    ).first()

    # Generic message to avoid revealing which usernames exist or have face login
    if not user or not user.face_enabled or not user.face_descriptor:
        return jsonify({'error': 'Face login not available for this account'}), 401

    if user.locked_until and user.locked_until > datetime.utcnow():
        return jsonify({
            'error': 'Account is temporarily locked',
            'locked_until': user.locked_until.isoformat(),
        }), 403

    if not user.is_active:
        return jsonify({'error': 'Account is disabled'}), 403

    distance = _euclidean_distance(user.face_descriptor, descriptor)

    if distance > FACE_MATCH_THRESHOLD:
        # Soft miss — only record a real failure (and possibly lock the
        # account) when the client tells us this was the final retry of
        # the session. Otherwise let them keep trying.
        if is_final:
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= 5:
                user.locked_until = datetime.utcnow() + timedelta(minutes=15)
            db.session.commit()

            log_audit(
                user_id=user.id,
                username=user.username,
                action='face_login_failed',
                resource='auth',
                status='failure',
                details={
                    'distance': round(distance, 4),
                    'threshold': FACE_MATCH_THRESHOLD,
                    'attempts': user.failed_login_attempts,
                },
            )

        return jsonify({
            'error': 'Face did not match',
            'distance': round(distance, 4),
            'miss': True,
        }), 401

    # Match — log the user in
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login = datetime.utcnow()
    db.session.commit()

    login_user(user, remember=False)

    access_token = create_access_token(identity=user.id, fresh=True)
    refresh_token = create_refresh_token(identity=user.id)

    log_audit(
        user_id=user.id,
        username=user.username,
        action='face_login_success',
        resource='auth',
        status='success',
        details={'distance': round(distance, 4)},
    )

    return jsonify({
        'success': True,
        'message': 'Face login successful',
        'user': user.to_dict(),
        'access_token': access_token,
        'refresh_token': refresh_token,
        'distance': round(distance, 4),
    }), 200


# ============================================================
# KYC REGISTRATION (one-shot account + ID proof + face)
# ============================================================
# Replaces the older 3-step "register, then add ID, then enroll face"
# flow. The new register page does everything in a single multipart
# POST so a fresh user lands on the dashboard with their KYC complete
# and face-login already enabled.

import json as _json
import os as __os
import uuid as _uuid
from werkzeug.utils import secure_filename
from flask import current_app, send_from_directory


_ID_PROOF_TYPES = {'passport', 'aadhaar', 'pan', 'driving_license', 'national_id'}
_ID_PROOF_ALLOWED_EXT = {'jpg', 'jpeg', 'png', 'webp'}
_ID_PROOF_ALLOWED_MIME = {'image/jpeg', 'image/png', 'image/webp'}
_ID_PROOF_MAX_BYTES = 5 * 1024 * 1024   # 5 MB per file


def _password_strength_ok(pw: str) -> tuple[bool, str]:
    """Conservative password rules: 8+ chars, mixed case, digit."""
    if not pw or len(pw) < 8:
        return False, 'Password must be at least 8 characters'
    if not any(c.islower() for c in pw):
        return False, 'Password must contain a lowercase letter'
    if not any(c.isupper() for c in pw):
        return False, 'Password must contain an uppercase letter'
    if not any(c.isdigit() for c in pw):
        return False, 'Password must contain a digit'
    return True, ''


@auth_bp.route('/api/register-kyc', methods=['POST'])
def api_register_kyc():
    """
    One-shot KYC + account creation.

    multipart/form-data fields:
      username, email, password, full_name        — account
      id_type   (passport|aadhaar|pan|driving_license|national_id)
      id_number (string, will be hashed)
      id_file   (image upload, jpg/png/webp, <= 5 MB)
      face_descriptor (JSON-encoded 128-dim array)

    Creates the user, stores the ID file under data/uploads/id_proofs/,
    saves the face descriptor (so face login works on next visit),
    auto-logs in, and returns a JWT pair.
    """
    form = request.form
    files = request.files

    username = (form.get('username') or '').strip()
    email = (form.get('email') or '').strip().lower()
    password = form.get('password') or ''
    full_name = (form.get('full_name') or '').strip() or None
    id_type = (form.get('id_type') or '').strip().lower()
    id_number = (form.get('id_number') or '').strip()
    descriptor_raw = form.get('face_descriptor') or ''
    id_file = files.get('id_file')

    # --- validate ---------------------------------------------------
    if not username or len(username) < 3 or len(username) > 50:
        return jsonify({'error': 'Username must be 3-50 characters'}), 400
    if not email or '@' not in email:
        return jsonify({'error': 'Valid email required'}), 400

    ok, msg = _password_strength_ok(password)
    if not ok:
        return jsonify({'error': msg}), 400

    if id_type not in _ID_PROOF_TYPES:
        return jsonify({'error': 'Invalid ID type'}), 400
    if not id_number or len(id_number) < 4:
        return jsonify({'error': 'ID number is required'}), 400
    if not id_file or not id_file.filename:
        return jsonify({'error': 'ID proof image is required'}), 400

    ext = id_file.filename.rsplit('.', 1)[-1].lower() if '.' in id_file.filename else ''
    if ext not in _ID_PROOF_ALLOWED_EXT:
        return jsonify({'error': 'ID proof must be jpg, png, or webp'}), 400
    if id_file.mimetype not in _ID_PROOF_ALLOWED_MIME:
        return jsonify({'error': 'Unsupported file type'}), 400

    # Cheap server-side size guard (Flask's MAX_CONTENT_LENGTH is the hard cap)
    id_file.stream.seek(0, 2)
    size = id_file.stream.tell()
    id_file.stream.seek(0)
    if size > _ID_PROOF_MAX_BYTES:
        return jsonify({'error': 'ID proof image must be 5 MB or smaller'}), 400
    if size < 1024:
        return jsonify({'error': 'ID proof image is too small / empty'}), 400

    # Face descriptor (optional — you can skip face on register and add it later)
    face_descriptor = None
    if descriptor_raw:
        try:
            parsed = _json.loads(descriptor_raw)
        except _json.JSONDecodeError:
            return jsonify({'error': 'Invalid face descriptor format'}), 400
        if not _validate_descriptor(parsed):
            return jsonify({'error': 'Invalid face descriptor (expected 128 numbers)'}), 400
        face_descriptor = [float(x) for x in parsed]

    # --- uniqueness -------------------------------------------------
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already taken'}), 409
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email already registered'}), 409

    viewer_role = Role.query.filter_by(name='viewer').first()
    if not viewer_role:
        return jsonify({'error': 'System configuration error'}), 500

    # --- save ID proof file ----------------------------------------
    upload_dir = current_app.config.get('ID_PROOF_UPLOAD_DIR')
    if not upload_dir:
        return jsonify({'error': 'Upload directory not configured'}), 500
    safe_username = secure_filename(username) or 'user'
    fname = f"{safe_username}_{_uuid.uuid4().hex[:12]}.{ext}"
    fpath = __os.path.join(upload_dir, fname)
    try:
        id_file.save(fpath)
    except Exception as e:
        return jsonify({'error': f'Could not save ID proof: {e}'}), 500

    # --- create user -----------------------------------------------
    user = User(
        username=username,
        email=email,
        full_name=full_name,
        role_id=viewer_role.id,
        is_active=True,
        is_verified=False,
    )
    user.set_password(password)
    user.id_proof_type = id_type
    user.id_proof_number_hash = generate_password_hash(id_number)
    user.id_proof_last4 = id_number[-4:]
    user.id_proof_file = f"id_proofs/{fname}"   # relative path under data/uploads
    user.kyc_completed_at = datetime.utcnow()

    if face_descriptor is not None:
        user.face_descriptor = face_descriptor
        user.face_enabled = True
        user.face_enrolled_at = datetime.utcnow()

    db.session.add(user)
    db.session.commit()

    # Seed banking so dashboard works on first login
    try:
        from src.banking import seed_user_banking
        seed_user_banking(user)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Banking seed failed for {user.username}: {e}")

    # Auto-login
    login_user(user, remember=False)
    user.last_login = datetime.utcnow()
    db.session.commit()

    access_token = create_access_token(identity=user.id, fresh=True)
    refresh_token = create_refresh_token(identity=user.id)

    log_audit(
        user_id=user.id,
        username=user.username,
        action='user_registered_kyc',
        resource='auth',
        status='success',
        details={'id_type': id_type, 'face_enrolled': face_descriptor is not None},
    )

    return jsonify({
        'success': True,
        'message': 'Registration & KYC complete',
        'user': user.to_dict(include_sensitive=True),
        'access_token': access_token,
        'refresh_token': refresh_token,
    }), 201


@auth_bp.route('/api/admin/id-proof/<int:user_id>', methods=['GET'])
@login_required
def api_admin_view_id_proof(user_id):
    """Admin-only: download the uploaded ID proof image for a user."""
    if not current_user.is_admin():
        return jsonify({'error': 'Forbidden'}), 403
    user = User.query.get_or_404(user_id)
    if not user.id_proof_file:
        return jsonify({'error': 'No ID proof on file'}), 404

    upload_root = __os.path.dirname(current_app.config['ID_PROOF_UPLOAD_DIR'])
    return send_from_directory(upload_root, user.id_proof_file, as_attachment=False)


# ============================================================
# HELPER FUNCTIONS
# ============================================================
def log_audit(user_id=None, username=None, action=None, resource=None, 
              resource_id=None, details=None, status='success'):
    """Log action to audit trail."""
    try:
        log = AuditLog(
            user_id=user_id,
            username=username,
            action=action,
            resource=resource,
            resource_id=resource_id,
            details=details,
            status=status,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
            request_method=request.method,
            request_path=request.path
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # Don't let audit logging failures break the app
        print(f"Audit log error: {e}")
