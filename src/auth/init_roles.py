"""
Initialize default roles and permissions in the database.
"""

from src.database import db
from src.database.models import Role, User


def init_default_roles():
    """Create default roles with permissions."""
    
    roles_config = [
        {
            'name': 'admin',
            'description': 'Full system access - manage users, models, and all features',
            'permissions': {
                'view_dashboard': True,
                'view_analytics': True,
                'view_transactions': True,
                'review_transactions': True,
                'manage_users': True,
                'manage_roles': True,
                'manage_models': True,
                'retrain_models': True,
                'view_audit_logs': True,
                'export_data': True,
                'manage_settings': True,
            }
        },
        {
            'name': 'analyst',
            'description': 'Fraud analyst - review transactions, view analytics, retrain models',
            'permissions': {
                'view_dashboard': True,
                'view_analytics': True,
                'view_transactions': True,
                'review_transactions': True,
                'manage_users': False,
                'manage_roles': False,
                'manage_models': False,
                'retrain_models': True,
                'view_audit_logs': False,
                'export_data': True,
                'manage_settings': False,
            }
        },
        {
            'name': 'viewer',
            'description': 'Read-only access - view dashboard and basic analytics',
            'permissions': {
                'view_dashboard': True,
                'view_analytics': True,
                'view_transactions': True,
                'review_transactions': False,
                'manage_users': False,
                'manage_roles': False,
                'manage_models': False,
                'retrain_models': False,
                'view_audit_logs': False,
                'export_data': False,
                'manage_settings': False,
            }
        },
    ]
    
    for role_config in roles_config:
        role = Role.query.filter_by(name=role_config['name']).first()
        if not role:
            role = Role(
                name=role_config['name'],
                description=role_config['description'],
                permissions=role_config['permissions']
            )
            db.session.add(role)
            print(f"Created role: {role_config['name']}")
        else:
            # Update permissions for existing role
            role.permissions = role_config['permissions']
            print(f"Updated role: {role_config['name']}")
    
    db.session.commit()


def create_default_admin(username='admin', email='admin@frauddetection.local', password='admin123'):
    """Create default admin user if none exists."""
    
    admin_role = Role.query.filter_by(name='admin').first()
    if not admin_role:
        print("Error: Admin role not found. Run init_default_roles() first.")
        return
    
    # Check if admin user exists
    admin = User.query.filter_by(username=username).first()
    if admin:
        print(f"Admin user '{username}' already exists.")
        return
    
    # Create admin user
    admin = User(
        username=username,
        email=email,
        full_name='System Administrator',
        role_id=admin_role.id,
        is_active=True,
        is_verified=True
    )
    admin.set_password(password)
    
    db.session.add(admin)
    db.session.commit()
    
    print(f"Created default admin user:")
    print(f"  Username: {username}")
    print(f"  Password: {password}")
    print(f"  Email: {email}")
    print(f"\n⚠️  IMPORTANT: Change the default password immediately!")
