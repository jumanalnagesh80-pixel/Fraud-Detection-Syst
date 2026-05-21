"""Authentication module initialization."""

from flask_login import LoginManager
from flask_jwt_extended import JWTManager

login_manager = LoginManager()
jwt = JWTManager()


def init_auth(app):
    """Initialize authentication with Flask app."""
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'
    
    jwt.init_app(app)
    
    from src.database.models import User
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
