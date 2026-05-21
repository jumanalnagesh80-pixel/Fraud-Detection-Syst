"""
RBAC middleware for request-level authorization checks.
"""

from functools import wraps
from flask import request, jsonify, g
from flask_login import current_user

from src.database import db
from src.database.models import AuditLog


def init_rbac_middleware(app):
    """Initialize RBAC middleware with Flask app."""
    
    @app.before_request
    def before_request():
        """Run before each request - set user context."""
        if current_user.is_authenticated:
            g.user = current_user
            g.user_id = current_user.id
            g.username = current_user.username
            g.role = current_user.role.name if current_user.role else None
        else:
            g.user = None
            g.user_id = None
            g.username = 'anonymous'
            g.role = None
    
    @app.after_request
    def after_request(response):
        """Run after each request - log API calls."""
        # Only log API calls, not static files
        if request.path.startswith('/api/') and request.method in ['POST', 'PUT', 'DELETE', 'PATCH']:
            try:
                status = 'success' if response.status_code < 400 else 'failure'
                
                # Don't log sensitive endpoints
                if '/api/login' not in request.path and '/api/register' not in request.path:
                    log_api_call(
                        action=f"{request.method}_{request.endpoint}",
                        resource=request.endpoint,
                        status=status,
                        details={
                            'status_code': response.status_code,
                            'content_length': response.content_length
                        }
                    )
            except Exception as e:
                # Don't let logging break the response
                app.logger.error(f"After request logging error: {e}")
        
        return response


def log_api_call(action, resource, status='success', resource_id=None, details=None):
    """Helper to log API calls to audit trail."""
    try:
        log = AuditLog(
            user_id=g.get('user_id'),
            username=g.get('username', 'anonymous'),
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
        print(f"API call logging error: {e}")


# Role-based route protection configuration
PROTECTED_ROUTES = {
    # Admin only
    '/admin': ['admin'],
    '/api/admin': ['admin'],
    '/api/users': ['admin'],
    '/api/roles': ['admin'],
    
    # Admin and Analyst
    '/api/transactions/review': ['admin', 'analyst'],
    '/api/model/retrain': ['admin', 'analyst'],
    
    # All authenticated users
    '/dashboard': ['admin', 'analyst', 'viewer'],
    '/api/predict': ['admin', 'analyst', 'viewer'],
    '/api/metrics': ['admin', 'analyst', 'viewer'],
}


def check_route_permission(path, user_role):
    """Check if user role has permission to access route."""
    # Check exact match first
    if path in PROTECTED_ROUTES:
        return user_role in PROTECTED_ROUTES[path]
    
    # Check prefix match
    for route_prefix, allowed_roles in PROTECTED_ROUTES.items():
        if path.startswith(route_prefix):
            return user_role in allowed_roles
    
    # Allow public routes by default
    return True
