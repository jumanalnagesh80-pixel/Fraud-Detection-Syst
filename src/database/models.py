"""
Database models for authentication, authorization, and audit logging.

Models:
- User: user accounts with authentication
- Role: user roles (admin, analyst, viewer)
- AuditLog: activity tracking for compliance
"""

from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from . import db


class Role(db.Model):
    """User roles for access control."""
    
    __tablename__ = 'roles'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(200))
    permissions = db.Column(db.JSON, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    users = db.relationship('User', back_populates='role', lazy='dynamic')
    
    def __repr__(self):
        return f'<Role {self.name}>'
    
    def has_permission(self, permission: str) -> bool:
        """Check if role has specific permission."""
        return self.permissions.get(permission, False)


class User(UserMixin, db.Model):
    """User accounts with authentication."""
    
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(100))
    
    # Role & Status
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    is_verified = db.Column(db.Boolean, default=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # Profile
    avatar_url = db.Column(db.String(255))
    phone = db.Column(db.String(20))
    department = db.Column(db.String(50))
    country = db.Column(db.String(10))           # ISO country code
    preferred_currency = db.Column(db.String(10), default='USD')
    job_title = db.Column(db.String(100))
    bio = db.Column(db.Text)
    
    # Security
    failed_login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime)
    security_question = db.Column(db.String(255))   # e.g., "What's your pet's name?"
    security_answer_hash = db.Column(db.String(255))
    two_factor_enabled = db.Column(db.Boolean, default=False)
    
    # Face authentication
    face_descriptor = db.Column(db.JSON)             # 128-dim float array from face-api.js
    face_enabled = db.Column(db.Boolean, default=False)
    face_enrolled_at = db.Column(db.DateTime)
    
    # Notification preferences
    notify_email = db.Column(db.Boolean, default=True)
    notify_high_risk = db.Column(db.Boolean, default=True)
    notify_critical_only = db.Column(db.Boolean, default=False)
    
    # Relationships
    role = db.relationship('Role', back_populates='users')
    audit_logs = db.relationship('AuditLog', back_populates='user', lazy='dynamic')
    
    def __repr__(self):
        return f'<User {self.username}>'
    
    def set_password(self, password: str) -> None:
        """Hash and set password."""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password: str) -> bool:
        """Verify password against hash."""
        return check_password_hash(self.password_hash, password)
    
    def set_security_answer(self, answer: str) -> None:
        """Hash and store security question answer (case-insensitive)."""
        normalized = (answer or "").strip().lower()
        self.security_answer_hash = generate_password_hash(normalized)
    
    def check_security_answer(self, answer: str) -> bool:
        """Verify security answer."""
        if not self.security_answer_hash:
            return False
        normalized = (answer or "").strip().lower()
        return check_password_hash(self.security_answer_hash, normalized)
    
    def has_permission(self, permission: str) -> bool:
        """Check if user has specific permission via role."""
        return self.role and self.role.has_permission(permission)
    
    def is_admin(self) -> bool:
        """Check if user is admin."""
        return self.role and self.role.name == 'admin'
    
    def is_analyst(self) -> bool:
        """Check if user is analyst."""
        return self.role and self.role.name == 'analyst'
    
    def to_dict(self, include_sensitive=False):
        """Convert user to dictionary."""
        data = {
            'id': self.id,
            'username': self.username,
            'email': self.email if include_sensitive else self._mask_email(),
            'full_name': self.full_name,
            'role': self.role.name if self.role else None,
            'is_active': self.is_active,
            'is_verified': self.is_verified,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'avatar_url': self.avatar_url,
            'department': self.department,
            'phone': self.phone,
            'country': self.country,
            'preferred_currency': self.preferred_currency,
            'job_title': self.job_title,
            'bio': self.bio,
            'two_factor_enabled': self.two_factor_enabled,
            'has_security_question': bool(self.security_question),
            'security_question': self.security_question if include_sensitive else None,
            'face_enabled': bool(self.face_enabled and self.face_descriptor),
            'face_enrolled_at': self.face_enrolled_at.isoformat() if self.face_enrolled_at else None,
            'notify_email': self.notify_email,
            'notify_high_risk': self.notify_high_risk,
            'notify_critical_only': self.notify_critical_only,
        }
        return data
    
    def _mask_email(self):
        """Mask email for privacy."""
        if not self.email:
            return None
        parts = self.email.split('@')
        if len(parts) != 2:
            return self.email
        username = parts[0]
        if len(username) <= 2:
            masked = username[0] + '*'
        else:
            masked = username[0] + '*' * (len(username) - 2) + username[-1]
        return f"{masked}@{parts[1]}"


class AuditLog(db.Model):
    """Activity audit log for compliance and security."""
    
    __tablename__ = 'audit_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    username = db.Column(db.String(80))  # Denormalized for deleted users
    
    # Action details
    action = db.Column(db.String(100), nullable=False, index=True)
    resource = db.Column(db.String(100), index=True)
    resource_id = db.Column(db.String(100))
    
    # Context
    details = db.Column(db.JSON)
    status = db.Column(db.String(20))  # success, failure, error
    
    # Request metadata
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    request_method = db.Column(db.String(10))
    request_path = db.Column(db.String(255))
    
    # Timestamp
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    user = db.relationship('User', back_populates='audit_logs')
    
    def __repr__(self):
        return f'<AuditLog {self.action} by {self.username}>'
    
    def to_dict(self):
        """Convert audit log to dictionary."""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'username': self.username,
            'action': self.action,
            'resource': self.resource,
            'resource_id': self.resource_id,
            'details': self.details,
            'status': self.status,
            'ip_address': self.ip_address,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class TransactionRecord(db.Model):
    """Persistent transaction records for history and audit."""
    
    __tablename__ = 'transaction_records'
    
    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    
    # Transaction data
    amount = db.Column(db.Float, nullable=False)
    country = db.Column(db.String(10))
    merchant_category = db.Column(db.String(50))
    device_type = db.Column(db.String(50))
    hour = db.Column(db.Integer)
    is_card_present = db.Column(db.Boolean)
    
    # Prediction results
    is_fraud = db.Column(db.Boolean, nullable=False)
    fraud_probability = db.Column(db.Float, nullable=False)
    risk_level = db.Column(db.String(20), nullable=False, index=True)
    decision = db.Column(db.String(20), nullable=False, index=True)
    model_score = db.Column(db.Float)
    rule_score = db.Column(db.Float)
    triggered_rules = db.Column(db.JSON)
    
    # Processing metadata
    latency_ms = db.Column(db.Float)
    processed_by = db.Column(db.String(80))  # username or 'system'
    processed_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    # Review status (for analyst workflow)
    review_status = db.Column(db.String(20), default='pending')  # pending, reviewed, escalated
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    reviewed_at = db.Column(db.DateTime)
    review_notes = db.Column(db.Text)
    
    def __repr__(self):
        return f'<Transaction {self.transaction_id}>'
    
    def to_dict(self):
        """Convert transaction to dictionary."""
        return {
            'id': self.id,
            'transaction_id': self.transaction_id,
            'amount': self.amount,
            'country': self.country,
            'merchant_category': self.merchant_category,
            'device_type': self.device_type,
            'hour': self.hour,
            'is_card_present': self.is_card_present,
            'is_fraud': self.is_fraud,
            'fraud_probability': self.fraud_probability,
            'risk_level': self.risk_level,
            'decision': self.decision,
            'model_score': self.model_score,
            'rule_score': self.rule_score,
            'triggered_rules': self.triggered_rules,
            'latency_ms': self.latency_ms,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
            'review_status': self.review_status,
            'reviewed_by': self.reviewed_by,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'review_notes': self.review_notes,
        }
