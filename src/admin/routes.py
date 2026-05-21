"""
Admin routes for user management, role management, and system monitoring.
"""

from datetime import datetime
from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user
from sqlalchemy import func, desc

from src.auth.decorators import admin_required
from src.database import db
from src.database.models import User, Role, AuditLog, TransactionRecord


admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


# ============================================================
# WEB ROUTES
# ============================================================

@admin_bp.route('/', methods=['GET'])
@admin_bp.route('/dashboard', methods=['GET'])
@login_required
@admin_required
def admin_dashboard():
    """Render admin dashboard page."""
    return render_template('admin/dashboard.html')


# ============================================================
# USER MANAGEMENT API
# ============================================================

@admin_bp.route('/api/users', methods=['GET'])
@login_required
@admin_required
def api_list_users():
    """List all users with pagination and filtering."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '').strip()
    role_filter = request.args.get('role', '').strip()
    status_filter = request.args.get('status', '').strip()
    
    query = User.query
    
    # Search filter
    if search:
        query = query.filter(
            (User.username.ilike(f'%{search}%')) |
            (User.email.ilike(f'%{search}%')) |
            (User.full_name.ilike(f'%{search}%'))
        )
    
    # Role filter
    if role_filter:
        query = query.join(Role).filter(Role.name == role_filter)
    
    # Status filter
    if status_filter == 'active':
        query = query.filter(User.is_active == True)
    elif status_filter == 'inactive':
        query = query.filter(User.is_active == False)
    
    # Pagination
    query = query.order_by(desc(User.created_at))
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'success': True,
        'users': [u.to_dict(include_sensitive=True) for u in pagination.items],
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': pagination.total,
            'pages': pagination.pages,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev,
        }
    }), 200


@admin_bp.route('/api/users/<int:user_id>', methods=['GET'])
@login_required
@admin_required
def api_get_user(user_id):
    """Get single user details."""
    user = User.query.get_or_404(user_id)
    
    # Get recent activity
    recent_logs = AuditLog.query.filter_by(user_id=user_id)\
        .order_by(desc(AuditLog.created_at))\
        .limit(10)\
        .all()
    
    return jsonify({
        'success': True,
        'user': user.to_dict(include_sensitive=True),
        'recent_activity': [log.to_dict() for log in recent_logs]
    }), 200


@admin_bp.route('/api/users/<int:user_id>', methods=['PUT'])
@login_required
@admin_required
def api_update_user(user_id):
    """Update user details."""
    user = User.query.get_or_404(user_id)
    data = request.get_json()
    
    # Don't allow editing yourself
    if user.id == current_user.id:
        return jsonify({'error': 'Cannot edit your own account via admin panel'}), 403
    
    # Update fields
    if 'full_name' in data:
        user.full_name = data['full_name']
    if 'email' in data:
        # Check email uniqueness
        existing = User.query.filter(User.email == data['email'], User.id != user_id).first()
        if existing:
            return jsonify({'error': 'Email already in use'}), 409
        user.email = data['email']
    if 'role_id' in data:
        role = Role.query.get(data['role_id'])
        if not role:
            return jsonify({'error': 'Invalid role'}), 400
        user.role_id = data['role_id']
    if 'is_active' in data:
        user.is_active = bool(data['is_active'])
    if 'is_verified' in data:
        user.is_verified = bool(data['is_verified'])
    if 'department' in data:
        user.department = data['department']
    if 'phone' in data:
        user.phone = data['phone']
    
    user.updated_at = datetime.utcnow()
    db.session.commit()
    
    # Log action
    _log_admin_action('user_updated', 'user', str(user.id), {
        'username': user.username,
        'updated_fields': list(data.keys())
    })
    
    return jsonify({
        'success': True,
        'message': 'User updated successfully',
        'user': user.to_dict(include_sensitive=True)
    }), 200


@admin_bp.route('/api/users/<int:user_id>', methods=['DELETE'])
@login_required
@admin_required
def api_delete_user(user_id):
    """Delete user account."""
    user = User.query.get_or_404(user_id)
    
    # Don't allow deleting yourself
    if user.id == current_user.id:
        return jsonify({'error': 'Cannot delete your own account'}), 403
    
    username = user.username
    
    # Log before deletion
    _log_admin_action('user_deleted', 'user', str(user.id), {
        'username': username,
        'email': user.email
    })
    
    db.session.delete(user)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': f'User {username} deleted successfully'
    }), 200


@admin_bp.route('/api/users/<int:user_id>/reset-password', methods=['POST'])
@login_required
@admin_required
def api_reset_user_password(user_id):
    """Reset user password to a temporary value."""
    user = User.query.get_or_404(user_id)
    data = request.get_json()
    
    new_password = data.get('new_password')
    if not new_password or len(new_password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400
    
    user.set_password(new_password)
    user.updated_at = datetime.utcnow()
    db.session.commit()
    
    _log_admin_action('password_reset', 'user', str(user.id), {
        'username': user.username,
        'reset_by_admin': True
    })
    
    return jsonify({
        'success': True,
        'message': 'Password reset successfully'
    }), 200


# ============================================================
# ROLE MANAGEMENT API
# ============================================================

@admin_bp.route('/api/roles', methods=['GET'])
@login_required
@admin_required
def api_list_roles():
    """List all roles."""
    roles = Role.query.order_by(Role.name).all()
    
    # Add user count to each role
    result = []
    for role in roles:
        role_dict = {
            'id': role.id,
            'name': role.name,
            'description': role.description,
            'permissions': role.permissions,
            'user_count': role.users.count(),
            'created_at': role.created_at.isoformat() if role.created_at else None
        }
        result.append(role_dict)
    
    return jsonify({
        'success': True,
        'roles': result
    }), 200


# ============================================================
# AUDIT LOG API
# ============================================================

@admin_bp.route('/api/audit-logs', methods=['GET'])
@login_required
@admin_required
def api_audit_logs():
    """Get audit logs with filtering and pagination."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    user_id = request.args.get('user_id', type=int)
    action = request.args.get('action', '').strip()
    status = request.args.get('status', '').strip()
    
    query = AuditLog.query
    
    if user_id:
        query = query.filter_by(user_id=user_id)
    if action:
        query = query.filter(AuditLog.action.ilike(f'%{action}%'))
    if status:
        query = query.filter_by(status=status)
    
    query = query.order_by(desc(AuditLog.created_at))
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'success': True,
        'logs': [log.to_dict() for log in pagination.items],
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': pagination.total,
            'pages': pagination.pages
        }
    }), 200


# ============================================================
# SYSTEM STATS API
# ============================================================

@admin_bp.route('/api/stats', methods=['GET'])
@login_required
@admin_required
def api_system_stats():
    """Get system statistics for admin dashboard."""
    # User stats
    total_users = User.query.count()
    active_users = User.query.filter_by(is_active=True).count()
    verified_users = User.query.filter_by(is_verified=True).count()
    
    # Role distribution
    role_distribution = db.session.query(
        Role.name, func.count(User.id)
    ).join(User).group_by(Role.name).all()
    
    # Recent registrations (last 30 days)
    from datetime import timedelta
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_registrations = User.query.filter(User.created_at >= thirty_days_ago).count()
    
    # Transaction stats
    total_transactions = TransactionRecord.query.count()
    fraud_transactions = TransactionRecord.query.filter_by(is_fraud=True).count()
    pending_reviews = TransactionRecord.query.filter_by(review_status='pending').count()
    
    # Recent audit activity
    recent_activity = AuditLog.query.order_by(desc(AuditLog.created_at)).limit(10).all()
    
    return jsonify({
        'success': True,
        'users': {
            'total': total_users,
            'active': active_users,
            'verified': verified_users,
            'recent_registrations': recent_registrations
        },
        'role_distribution': dict(role_distribution),
        'transactions': {
            'total': total_transactions,
            'fraud_detected': fraud_transactions,
            'pending_reviews': pending_reviews,
            'fraud_rate': round(fraud_transactions / total_transactions, 4) if total_transactions else 0
        },
        'recent_activity': [log.to_dict() for log in recent_activity]
    }), 200


# ============================================================
# HELPERS
# ============================================================

def _log_admin_action(action, resource, resource_id, details=None):
    """Log admin action to audit trail."""
    try:
        log = AuditLog(
            user_id=current_user.id,
            username=current_user.username,
            action=action,
            resource=resource,
            resource_id=resource_id,
            details=details,
            status='success',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
            request_method=request.method,
            request_path=request.path
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Admin action logging error: {e}")
