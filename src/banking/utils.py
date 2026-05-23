"""
Banking helpers — number generation, masking, and hashing.

These helpers are intentionally **demo-grade**:

* Account numbers and IBANs use a simple checksum, not a real bank's
  format, so they cannot collide with real-world numbers.
* Card numbers use the well-known test BIN ranges published by Stripe /
  Adyen (e.g. 4242 4242 4242 4242). They pass the Luhn check but are
  flagged as test cards by every real card processor.
* Full PANs are *never* persisted. Only ``last4`` and a SHA-256 hash
  are stored. CVVs are bcrypt-hashed.
"""

from __future__ import annotations

import hashlib
import random
import secrets
from datetime import datetime
from typing import Tuple

from werkzeug.security import generate_password_hash


# ---------------------------------------------------------------------
# Test BINs (first 6 digits) — these are the *public* test numbers used
# by Stripe / Adyen / etc. Real card processors recognise them as test.
# ---------------------------------------------------------------------
TEST_BINS = {
    "visa":       ["424242", "400000", "401288"],
    "mastercard": ["555555", "520000", "510510"],
    "amex":       ["378282", "371449"],            # 15 digits
    "discover":   ["601111"],
}

CARD_LENGTHS = {
    "visa": 16, "mastercard": 16, "discover": 16,
    "amex": 15,
}


# ---------------------------------------------------------------------
# Luhn checksum (used by all real card numbers and most account schemes)
# ---------------------------------------------------------------------
def luhn_checksum(digits: str) -> int:
    """Return the Luhn check digit for the given digit string."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10


def luhn_valid(number: str) -> bool:
    if not number or not number.isdigit():
        return False
    return luhn_checksum(number[:-1]) == int(number[-1])


# ---------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------
def generate_account_number(length: int = 12) -> str:
    """Generate a random numeric account number."""
    body = ''.join(secrets.choice('0123456789') for _ in range(length - 1))
    return body + str(luhn_checksum(body))


def generate_iban(country: str = 'US', account_number: str | None = None) -> str:
    """Build a demo IBAN: <country><check_digits><bank><account>.

    Real IBANs use a mod-97 algorithm — for the demo we use random check
    digits since no real bank validates these.
    """
    cc = (country or 'US')[:2].upper()
    if cc.isdigit() or len(cc) < 2:
        cc = 'US'
    check = f"{random.randint(10, 99)}"
    bank_code = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=4))
    body = (account_number or generate_account_number(10))[:14].zfill(14)
    return f"{cc}{check}{bank_code}{body}"


def generate_routing_number() -> str:
    """Generate a demo 9-digit routing number."""
    return ''.join(secrets.choice('0123456789') for _ in range(9))


def generate_card_number(brand: str = 'visa') -> str:
    """Generate a Luhn-valid test card number for the given brand."""
    brand = (brand or 'visa').lower()
    if brand not in TEST_BINS:
        brand = 'visa'
    bin_prefix = random.choice(TEST_BINS[brand])
    length = CARD_LENGTHS[brand]
    body = bin_prefix + ''.join(secrets.choice('0123456789') for _ in range(length - len(bin_prefix) - 1))
    return body + str(luhn_checksum(body))


def generate_cvv(brand: str = 'visa') -> str:
    """Generate a 3- or 4-digit CVV (4 for Amex)."""
    digits = 4 if (brand or '').lower() == 'amex' else 3
    return ''.join(secrets.choice('0123456789') for _ in range(digits))


def generate_expiry(years_ahead: int = 4) -> Tuple[int, int]:
    """Return (month, year) for a card valid ``years_ahead`` years."""
    now = datetime.utcnow()
    month = random.randint(1, 12)
    year = now.year + random.randint(2, max(2, years_ahead))
    return month, year


# ---------------------------------------------------------------------
# Hashing & masking
# ---------------------------------------------------------------------
def hash_pan(pan: str) -> str:
    """Return a SHA-256 hash of the full PAN (used to detect duplicates)."""
    return hashlib.sha256((pan or '').encode('utf-8')).hexdigest()


def hash_cvv(cvv: str) -> str:
    """Bcrypt-hash a CVV. Comparable but not reversible."""
    return generate_password_hash(cvv or '')


def mask_pan(pan: str) -> str:
    """Mask all but the last 4 digits, formatted in groups of 4."""
    if not pan:
        return ''
    last4 = pan[-4:]
    digits = len(pan)
    masked = ('*' * (digits - 4)) + last4
    # group into 4s for display, e.g. **** **** **** 4242
    return ' '.join(masked[i:i + 4] for i in range(0, digits, 4))


def last4(pan: str) -> str:
    return (pan or '')[-4:]
