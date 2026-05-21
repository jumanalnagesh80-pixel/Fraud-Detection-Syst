"""
Authentication routes: login, logout, register, password management.
"""

from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from flask_jwt_extended import create_access_token, create_refresh_token, jwt_required, get_jwt_identity

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
        return redirect(url_for('main.dashboard'))
    return render_template('auth/login.html')


@auth_bp.route('/register', methods=['GET'])
def register():
    """Render registration page."""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
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
