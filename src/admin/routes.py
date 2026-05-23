"""
Admin routes for user management, role management, and system monitoring.
"""

from datetime import datetime, timedelta
from flask import Blueprint, current_app, request, jsonify, render_template
from flask_login import login_required, current_user
from sqlalchemy import func, desc

from src.auth.decorators import admin_required
from src.database import db
from src.database.models import (
    AuditLog, BankAccount, Card, Role, TransactionRecord, User,
)


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
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_registrations = User.query.filter(User.created_at >= thirty_days_ago).count()
    
    # Transaction stats
    total_transactions = TransactionRecord.query.count()
    fraud_transactions = TransactionRecord.query.filter_by(is_fraud=True).count()
    pending_reviews = TransactionRecord.query.filter_by(review_status='pending').count()
    
    # Banking stats
    total_accounts = BankAccount.query.count()
    total_cards = Card.query.count()
    blocked_cards = Card.query.filter_by(status='blocked').count()
    frozen_cards = Card.query.filter_by(status='frozen').count()
    total_balance = float(db.session.query(func.coalesce(func.sum(BankAccount.balance), 0))
                          .filter_by(status='active').scalar() or 0)

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
        'banking': {
            'total_accounts': total_accounts,
            'total_cards': total_cards,
            'blocked_cards': blocked_cards,
            'frozen_cards': frozen_cards,
            'total_balance': round(total_balance, 2),
        },
        'recent_activity': [log.to_dict() for log in recent_activity]
    }), 200


# ============================================================
# BANKING (admin view across all users)
# ============================================================

@admin_bp.route('/api/banking/accounts', methods=['GET'])
@login_required
@admin_required
def api_admin_list_accounts():
    """List all bank accounts across users with optional filters."""
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 200)
    user_id = request.args.get('user_id', type=int)
    status = request.args.get('status', '').strip()

    q = BankAccount.query
    if user_id:
        q = q.filter_by(user_id=user_id)
    if status:
        q = q.filter_by(status=status)
    q = q.order_by(desc(BankAccount.opened_at))
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)

    # Lookup usernames in bulk for nicer rendering
    user_ids = {a.user_id for a in pagination.items}
    users = {u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}

    out = []
    for a in pagination.items:
        d = a.to_dict(include_full_number=True)
        u = users.get(a.user_id)
        d['username'] = u.username if u else None
        d['user_full_name'] = u.full_name if u else None
        out.append(d)

    return jsonify({
        'success': True,
        'accounts': out,
        'pagination': {
            'page': page, 'per_page': per_page,
            'total': pagination.total, 'pages': pagination.pages,
        },
    })


@admin_bp.route('/api/banking/accounts/<int:account_id>/freeze', methods=['POST'])
@login_required
@admin_required
def api_admin_freeze_account(account_id):
    return _admin_set_account_status(account_id, 'frozen')


@admin_bp.route('/api/banking/accounts/<int:account_id>/activate', methods=['POST'])
@login_required
@admin_required
def api_admin_activate_account(account_id):
    return _admin_set_account_status(account_id, 'active')


@admin_bp.route('/api/banking/cards', methods=['GET'])
@login_required
@admin_required
def api_admin_list_cards():
    """List all cards across users."""
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 200)
    user_id = request.args.get('user_id', type=int)
    status = request.args.get('status', '').strip()

    q = Card.query
    if user_id:
        q = q.filter_by(user_id=user_id)
    if status:
        q = q.filter_by(status=status)
    q = q.order_by(desc(Card.issued_at))
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)

    user_ids = {c.user_id for c in pagination.items}
    users = {u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}

    out = []
    for c in pagination.items:
        d = c.to_dict()
        u = users.get(c.user_id)
        d['username'] = u.username if u else None
        d['user_full_name'] = u.full_name if u else None
        out.append(d)

    return jsonify({
        'success': True,
        'cards': out,
        'pagination': {
            'page': page, 'per_page': per_page,
            'total': pagination.total, 'pages': pagination.pages,
        },
    })


@admin_bp.route('/api/banking/cards/<int:card_id>/block', methods=['POST'])
@login_required
@admin_required
def api_admin_block_card(card_id):
    """Permanently block a card (e.g. confirmed fraud)."""
    data = request.get_json(silent=True) or {}
    reason = (data.get('reason') or 'Blocked by administrator').strip()[:255]
    return _admin_set_card_status(card_id, 'blocked', reason)


@admin_bp.route('/api/banking/cards/<int:card_id>/unblock', methods=['POST'])
@login_required
@admin_required
def api_admin_unblock_card(card_id):
    return _admin_set_card_status(card_id, 'active', None)


@admin_bp.route('/api/banking/cards/<int:card_id>/freeze', methods=['POST'])
@login_required
@admin_required
def api_admin_freeze_card(card_id):
    return _admin_set_card_status(card_id, 'frozen', 'Frozen by administrator')


# ============================================================
# TRANSACTIONS (admin view)
# ============================================================

@admin_bp.route('/api/transactions', methods=['GET'])
@login_required
@admin_required
def api_admin_transactions():
    """All transactions across users with filters."""
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 200)
    user_id = request.args.get('user_id', type=int)
    risk = request.args.get('risk_level', '').strip()
    decision = request.args.get('decision', '').strip()
    only_fraud = request.args.get('only_fraud', '').lower() in ('1', 'true', 'yes')

    q = TransactionRecord.query
    if user_id:
        q = q.filter_by(user_id=user_id)
    if risk:
        q = q.filter_by(risk_level=risk)
    if decision:
        q = q.filter_by(decision=decision)
    if only_fraud:
        q = q.filter_by(is_fraud=True)
    q = q.order_by(desc(TransactionRecord.processed_at))
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)

    user_ids = {t.user_id for t in pagination.items if t.user_id}
    users = {u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}

    items = []
    for t in pagination.items:
        d = t.to_dict()
        u = users.get(t.user_id) if t.user_id else None
        d['username'] = u.username if u else None
        items.append(d)

    return jsonify({
        'success': True,
        'transactions': items,
        'pagination': {
            'page': page, 'per_page': per_page,
            'total': pagination.total, 'pages': pagination.pages,
        },
    })


@admin_bp.route('/api/transactions/<int:txn_id>/review', methods=['POST'])
@login_required
@admin_required
def api_admin_review_transaction(txn_id):
    """Mark a transaction as reviewed and optionally release/decline held funds."""
    txn = TransactionRecord.query.get_or_404(txn_id)
    data = request.get_json(silent=True) or {}
    action = (data.get('action') or 'mark_reviewed').strip()
    notes = (data.get('notes') or '').strip()[:1000]

    txn.review_status = 'reviewed'
    txn.reviewed_by = current_user.id
    txn.reviewed_at = datetime.utcnow()
    if notes:
        txn.review_notes = notes

    # Release/decline held funds (only meaningful for held_for_review records)
    if action in ('approve', 'release') and txn.decision == 'held_for_review':
        if txn.bank_account_id:
            account = BankAccount.query.get(txn.bank_account_id)
            if account:
                account.balance -= txn.amount
                # available_balance was already deducted at "review" decision
                txn.decision = 'approved'
    elif action in ('decline', 'reject') and txn.decision == 'held_for_review':
        if txn.bank_account_id:
            account = BankAccount.query.get(txn.bank_account_id)
            if account:
                # restore the held funds
                account.available_balance += txn.amount
                txn.decision = 'declined'

    db.session.commit()
    _log_admin_action('transaction_reviewed', 'transaction', str(txn.id), {
        'action': action, 'final_decision': txn.decision,
    })
    return jsonify({'success': True, 'transaction': txn.to_dict()})


# ============================================================
# MODEL MANAGEMENT
# ============================================================

@admin_bp.route('/api/model/info', methods=['GET'])
@login_required
@admin_required
def api_admin_model_info():
    model = current_app.config.get('FRAUD_MODEL')
    if model is None:
        return jsonify({'error': 'model not loaded'}), 503
    return jsonify({
        'is_trained': model.is_trained,
        'metrics': model.metrics_,
        'feature_importance': model.feature_importance_,
        'thresholds': model.THRESHOLDS,
    })


@admin_bp.route('/api/model/retrain', methods=['POST'])
@login_required
@admin_required
def api_admin_model_retrain():
    """Retrain the fraud model on freshly generated synthetic data."""
    from src.data_processing import generate_synthetic_transactions
    from src.models import FraudModel

    data = request.get_json(silent=True) or {}
    samples = max(1000, min(int(data.get('samples', 8000)), 50000))
    fraud_rate = max(0.0, min(float(data.get('fraud_rate', 0.05)), 0.5))

    df = generate_synthetic_transactions(n_transactions=samples,
                                         fraud_rate=fraud_rate)
    model = FraudModel()
    metrics = model.train(df)
    current_app.config['FRAUD_MODEL'] = model

    _log_admin_action('model_retrained', 'fraud_model', None, {
        'samples': samples, 'fraud_rate': fraud_rate, 'metrics': metrics,
    })
    return jsonify({'success': True, 'metrics': metrics,
                    'feature_importance': model.feature_importance_})


# ============================================================
# LIVE STREAM (system-wide control)
# ============================================================

@admin_bp.route('/api/live-streams', methods=['GET'])
@login_required
@admin_required
def api_admin_live_streams():
    """Show every running per-user live stream."""
    from src.banking import get_live_stream_manager
    mgr = get_live_stream_manager()
    out = []
    # Inspect the registry without locking the manager (read-only)
    workers = list(getattr(mgr, '_workers', {}).items())
    for uid, w in workers:
        if w.is_alive():
            user = User.query.get(uid)
            out.append({
                'user_id': uid,
                'username': user.username if user else None,
                'rate_per_min': w.rate_per_min,
                'fraud_rate': w.fraud_rate,
                'count': w.count,
                'started_at': w.started_at.isoformat() if w.started_at else None,
            })
    return jsonify({'success': True, 'streams': out, 'count': len(out)})


@admin_bp.route('/api/live-streams/stop-all', methods=['POST'])
@login_required
@admin_required
def api_admin_live_streams_stop_all():
    from src.banking import get_live_stream_manager
    get_live_stream_manager().stop_all()
    _log_admin_action('live_streams_stopped_all', 'live_stream', None, None)
    return jsonify({'success': True, 'message': 'All live streams stopped'})


# ============================================================
# HELPERS
# ============================================================

def _admin_set_account_status(account_id: int, status: str):
    """Admin helper: change a bank account's status."""
    account = BankAccount.query.get_or_404(account_id)
    account.status = status
    if status == 'active':
        account.closed_at = None
    db.session.commit()
    _log_admin_action('account_status_changed', 'bank_account', str(account.id),
                      {'status': status})
    _publish_admin_event('admin.account_status', {
        'account_id': account.id, 'status': status, 'user_id': account.user_id,
    })
    return jsonify({'success': True, 'account': account.to_dict()})


def _admin_set_card_status(card_id: int, status: str, reason):
    """Admin helper: change a card's status."""
    card = Card.query.get_or_404(card_id)
    card.status = status
    card.blocked_reason = reason
    db.session.commit()
    _log_admin_action('card_status_changed', 'card', str(card.id),
                      {'status': status, 'reason': reason})
    _publish_admin_event('admin.card_status', {
        'card_id': card.id, 'status': status, 'reason': reason,
        'user_id': card.user_id,
    })
    return jsonify({'success': True, 'card': card.to_dict()})


def _publish_admin_event(event_type: str, payload: dict) -> None:
    """Best-effort SSE publish — never let bus issues break a response."""
    try:
        bus = current_app.config.get('EVENT_BUS')
        if bus is not None:
            bus.publish(event_type, payload)
    except Exception:
        pass


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
