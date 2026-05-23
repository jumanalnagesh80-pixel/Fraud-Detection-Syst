"""Flask API blueprint."""

from .routes import create_api_blueprint
from .extras_routes import create_extras_blueprint, push_notification
from .sse_routes import create_sse_blueprint

__all__ = [
    "create_api_blueprint",
    "create_extras_blueprint",
    "create_sse_blueprint",
    "push_notification",
]
