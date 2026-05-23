"""
Seed a freshly-registered user with a default checking account and debit card.

This makes the system feel like a real bank from the first login:
balance is non-zero, a usable card exists, and the dashboard is
populated immediately when the user starts transacting.
"""

from __future__ import annotations

import logging

from src.database import db
from src.database.models import BankAccount, Card, User

from . import utils


log = logging.getLogger(__name__)

# Starting balance for new accounts (USD). Treat this as demo cash.
DEFAULT_OPENING_BALANCE = 5000.0
DEFAULT_DAILY_CARD_LIMIT = 2500.0


def seed_user_banking(user: User, force: bool = False) -> dict:
    """Ensure ``user`` has at least one account and one card.

    Idempotent: if the user already has an account/card, nothing
    happens unless ``force=True``.

    Returns a summary dict so callers can audit-log the action.
    """
    if not user or not user.id:
        return {"created_account": False, "created_card": False}

    summary = {"created_account": False, "created_card": False,
               "account_id": None, "card_id": None}

    account = user.bank_accounts.first() if user.bank_accounts else None
    if account is None or force:
        account = _create_default_account(user)
        summary["created_account"] = True
    summary["account_id"] = account.id

    card = account.cards.first()
    if card is None or force:
        card = _create_default_card(user, account)
        summary["created_card"] = True
    summary["card_id"] = card.id

    return summary


def _create_default_account(user: User) -> BankAccount:
    """Create a primary checking account."""
    country = (user.country or 'US').upper()
    currency = user.preferred_currency or 'USD'

    # ensure unique account_number even on retries
    account_number = _unique_account_number()
    iban = utils.generate_iban(country, account_number)

    account = BankAccount(
        user_id=user.id,
        account_number=account_number,
        iban=iban,
        routing_number=utils.generate_routing_number(),
        nickname='Primary Checking',
        account_type='checking',
        currency=currency,
        country=country,
        balance=DEFAULT_OPENING_BALANCE,
        available_balance=DEFAULT_OPENING_BALANCE,
        status='active',
        is_primary=True,
    )
    db.session.add(account)
    db.session.flush()  # need the id before creating the card
    log.info("Seeded checking account %s for user %s", account.account_number, user.username)
    return account


def _create_default_card(user: User, account: BankAccount) -> Card:
    """Issue a primary debit card linked to the account."""
    pan = utils.generate_card_number('visa')
    month, year = utils.generate_expiry()
    cardholder = user.full_name or user.username or 'Cardholder'

    card = Card(
        user_id=user.id,
        account_id=account.id,
        card_number_masked=utils.mask_pan(pan),
        last4=utils.last4(pan),
        pan_hash=utils.hash_pan(pan),
        cvv_hash=utils.hash_cvv(utils.generate_cvv('visa')),
        expiry_month=month,
        expiry_year=year,
        card_type='debit',
        brand='visa',
        cardholder_name=cardholder.upper()[:120],
        nickname='Primary Debit',
        daily_limit=DEFAULT_DAILY_CARD_LIMIT,
        daily_spent=0.0,
        international_enabled=False,
        contactless_enabled=True,
        online_enabled=True,
        status='active',
    )
    db.session.add(card)
    db.session.flush()
    log.info("Issued debit card **** %s for user %s", card.last4, user.username)
    return card


def _unique_account_number(max_tries: int = 6) -> str:
    """Generate an account number that doesn't collide with existing rows."""
    for _ in range(max_tries):
        candidate = utils.generate_account_number(12)
        if not BankAccount.query.filter_by(account_number=candidate).first():
            return candidate
    # extremely unlikely fallback
    return utils.generate_account_number(14)
