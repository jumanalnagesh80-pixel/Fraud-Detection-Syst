"""
Authorization decorators for role-based access control.
"""

from functools import wraps
from flask import jsonify, abort
from flask_login import current_user


def role_required(*roles):
    """
    Decorator to require specific role(s).
    
    Usage:
        @role_required('admin')
        @role_required('admin', 'analyst')
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
            
            if current_user.role.name not in roles:
                return jsonify({'error': 'Insufficient permissions'}), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def permission_required(permission):
    """
    Decorator to require specific permission.
    
    Usage:
        @permission_required('manage_users')
        @permission_required('view_analytics')
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
            
            if not current_user.has_permission(permission):
                return jsonify({'error': f'Permission "{permission}" required'}), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def admin_required(f):
    """Decorator to require admin role."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'error': 'Authentication required'}), 401
        
        if not current_user.is_admin():
            return jsonify({'error': 'Admin access required'}), 403
        
        return f(*args, **kwargs)
    return decorated_function
