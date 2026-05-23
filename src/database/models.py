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
    bank_accounts = db.relationship('BankAccount', back_populates='user', lazy='dynamic',
                                    cascade='all, delete-orphan')
    cards = db.relationship('Card', back_populates='user', lazy='dynamic',
                            cascade='all, delete-orphan')
    
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
    
    # Optional banking links (null for synthetic / simulator transactions)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    bank_account_id = db.Column(db.Integer, db.ForeignKey('bank_accounts.id'), index=True)
    card_id = db.Column(db.Integer, db.ForeignKey('cards.id'), index=True)
    merchant_name = db.Column(db.String(120))
    currency = db.Column(db.String(10), default='USD')

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
            'user_id': self.user_id,
            'bank_account_id': self.bank_account_id,
            'card_id': self.card_id,
            'merchant_name': self.merchant_name,
            'currency': self.currency,
            'review_status': self.review_status,
            'reviewed_by': self.reviewed_by,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'review_notes': self.review_notes,
        }


# ============================================================
# BANKING MODELS - real bank accounts and cards
# ============================================================

class BankAccount(db.Model):
    """A user's bank account.

    Account numbers and IBANs are generated at creation time. Balance
    changes happen only through approved transactions in the banking
    routes — never directly from the UI.
    """

    __tablename__ = 'bank_accounts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Account identification
    account_number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    iban = db.Column(db.String(34), unique=True)              # international banking number
    routing_number = db.Column(db.String(20))                  # ABA / SWIFT-equivalent
    nickname = db.Column(db.String(80))                        # user-chosen label

    # Account properties
    account_type = db.Column(db.String(20), default='checking', nullable=False)  # checking | savings
    currency = db.Column(db.String(10), default='USD', nullable=False)
    country = db.Column(db.String(10), default='US')
    balance = db.Column(db.Float, default=0.0, nullable=False)
    available_balance = db.Column(db.Float, default=0.0, nullable=False)  # balance minus holds

    # Status
    status = db.Column(db.String(20), default='active', nullable=False)  # active | frozen | closed
    is_primary = db.Column(db.Boolean, default=False)

    # Timestamps
    opened_at = db.Column(db.DateTime, default=datetime.utcnow)
    closed_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', back_populates='bank_accounts')
    cards = db.relationship('Card', back_populates='account', lazy='dynamic',
                            cascade='all, delete-orphan')

    def __repr__(self):
        return f'<BankAccount {self.account_number} ({self.account_type})>'

    @property
    def masked_account_number(self) -> str:
        """Return the account number with all but the last 4 digits masked."""
        if not self.account_number or len(self.account_number) < 5:
            return self.account_number or ''
        return '****' + self.account_number[-4:]

    def to_dict(self, include_full_number: bool = False) -> dict:
        return {
            'id': self.id,
            'user_id': self.user_id,
            'account_number': self.account_number if include_full_number else self.masked_account_number,
            'iban': self.iban,
            'routing_number': self.routing_number,
            'nickname': self.nickname,
            'account_type': self.account_type,
            'currency': self.currency,
            'country': self.country,
            'balance': round(self.balance, 2),
            'available_balance': round(self.available_balance, 2),
            'status': self.status,
            'is_primary': self.is_primary,
            'opened_at': self.opened_at.isoformat() if self.opened_at else None,
            'card_count': self.cards.count() if self.id else 0,
        }


class Card(db.Model):
    """A debit or credit card tied to a bank account.

    Card numbers (PAN) are stored masked. Only the last 4 digits and a
    SHA-256 hash of the full number are kept — the full PAN is never
    persisted, mirroring real-world PCI-DSS handling.
    """

    __tablename__ = 'cards'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    account_id = db.Column(db.Integer, db.ForeignKey('bank_accounts.id'), nullable=False, index=True)

    # Card identification (only the masked form and last4 are queryable)
    card_number_masked = db.Column(db.String(25), nullable=False)        # e.g. "**** **** **** 4242"
    last4 = db.Column(db.String(4), nullable=False, index=True)
    pan_hash = db.Column(db.String(128))                                 # sha-256 of full PAN
    cvv_hash = db.Column(db.String(255))                                 # bcrypt hash
    expiry_month = db.Column(db.Integer, nullable=False)
    expiry_year = db.Column(db.Integer, nullable=False)

    # Card properties
    card_type = db.Column(db.String(20), default='debit', nullable=False)   # debit | credit | prepaid
    brand = db.Column(db.String(20), default='visa')                        # visa | mastercard | amex | discover
    cardholder_name = db.Column(db.String(120))
    nickname = db.Column(db.String(80))                                     # e.g. "Travel card"

    # Limits and security
    daily_limit = db.Column(db.Float, default=2000.0)
    daily_spent = db.Column(db.Float, default=0.0)
    daily_reset_at = db.Column(db.DateTime, default=datetime.utcnow)
    international_enabled = db.Column(db.Boolean, default=False)
    contactless_enabled = db.Column(db.Boolean, default=True)
    online_enabled = db.Column(db.Boolean, default=True)

    # Status
    status = db.Column(db.String(20), default='active', nullable=False)
    # active | frozen | blocked | expired | reported_lost
    blocked_reason = db.Column(db.String(255))

    # Timestamps
    issued_at = db.Column(db.DateTime, default=datetime.utcnow)
    activated_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', back_populates='cards')
    account = db.relationship('BankAccount', back_populates='cards')

    def __repr__(self):
        return f'<Card {self.brand} **** {self.last4} ({self.status})>'

    @property
    def is_expired(self) -> bool:
        now = datetime.utcnow()
        if self.expiry_year < now.year:
            return True
        if self.expiry_year == now.year and self.expiry_month < now.month:
            return True
        return False

    @property
    def is_usable(self) -> bool:
        return self.status == 'active' and not self.is_expired

    def reset_daily_spent_if_needed(self) -> None:
        """Roll the daily spent counter at UTC midnight."""
        now = datetime.utcnow()
        if not self.daily_reset_at or self.daily_reset_at.date() < now.date():
            self.daily_spent = 0.0
            self.daily_reset_at = now

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'user_id': self.user_id,
            'account_id': self.account_id,
            'card_number_masked': self.card_number_masked,
            'last4': self.last4,
            'expiry_month': self.expiry_month,
            'expiry_year': self.expiry_year,
            'expiry_display': f"{self.expiry_month:02d}/{self.expiry_year % 100:02d}",
            'card_type': self.card_type,
            'brand': self.brand,
            'cardholder_name': self.cardholder_name,
            'nickname': self.nickname,
            'daily_limit': self.daily_limit,
            'daily_spent': round(self.daily_spent, 2),
            'daily_remaining': round(max(0.0, (self.daily_limit or 0.0) - (self.daily_spent or 0.0)), 2),
            'international_enabled': self.international_enabled,
            'contactless_enabled': self.contactless_enabled,
            'online_enabled': self.online_enabled,
            'status': self.status,
            'is_expired': self.is_expired,
            'blocked_reason': self.blocked_reason,
            'issued_at': self.issued_at.isoformat() if self.issued_at else None,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
        }
