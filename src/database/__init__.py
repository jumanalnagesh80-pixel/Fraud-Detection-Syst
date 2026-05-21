"""Database initialization and configuration."""

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

db = SQLAlchemy()
migrate = Migrate()


def init_db(app):
    """Initialize database with Flask app."""
    db.init_app(app)
    migrate.init_app(app, db)
    
    with app.app_context():
        db.create_all()
