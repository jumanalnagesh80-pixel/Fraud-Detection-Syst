"""
Comprehensive country data for global fraud detection.

Provides:
- 60+ countries with ISO codes, currencies, regions
- Country-level fraud risk scores
- Currency exchange rates (approximate, USD-based)
- Region groupings for geographic analytics
"""

from __future__ import annotations
from typing import Dict, List, Optional


# Risk levels (0.0 = safest, 1.0 = highest risk)
# Based on AML, sanctions, and fraud-prevalence indicators
COUNTRIES: Dict[str, Dict] = {
    # ========== NORTH AMERICA ==========
    "US": {"name": "United States",     "currency": "USD", "symbol": "$",  "flag": "🇺🇸", "region": "North America", "risk": 0.15, "rate": 1.00},
    "CA": {"name": "Canada",            "currency": "CAD", "symbol": "C$", "flag": "🇨🇦", "region": "North America", "risk": 0.12, "rate": 1.36},
    "MX": {"name": "Mexico",            "currency": "MXN", "symbol": "$",  "flag": "🇲🇽", "region": "North America", "risk": 0.45, "rate": 17.50},

    # ========== EUROPE ==========
    "GB": {"name": "United Kingdom",    "currency": "GBP", "symbol": "£",  "flag": "🇬🇧", "region": "Europe", "risk": 0.18, "rate": 0.79},
    "DE": {"name": "Germany",           "currency": "EUR", "symbol": "€",  "flag": "🇩🇪", "region": "Europe", "risk": 0.12, "rate": 0.92},
    "FR": {"name": "France",            "currency": "EUR", "symbol": "€",  "flag": "🇫🇷", "region": "Europe", "risk": 0.18, "rate": 0.92},
    "IT": {"name": "Italy",             "currency": "EUR", "symbol": "€",  "flag": "🇮🇹", "region": "Europe", "risk": 0.22, "rate": 0.92},
    "ES": {"name": "Spain",             "currency": "EUR", "symbol": "€",  "flag": "🇪🇸", "region": "Europe", "risk": 0.20, "rate": 0.92},
    "NL": {"name": "Netherlands",       "currency": "EUR", "symbol": "€",  "flag": "🇳🇱", "region": "Europe", "risk": 0.10, "rate": 0.92},
    "BE": {"name": "Belgium",           "currency": "EUR", "symbol": "€",  "flag": "🇧🇪", "region": "Europe", "risk": 0.14, "rate": 0.92},
    "CH": {"name": "Switzerland",       "currency": "CHF", "symbol": "Fr", "flag": "🇨🇭", "region": "Europe", "risk": 0.08, "rate": 0.88},
    "SE": {"name": "Sweden",            "currency": "SEK", "symbol": "kr", "flag": "🇸🇪", "region": "Europe", "risk": 0.10, "rate": 10.50},
    "NO": {"name": "Norway",            "currency": "NOK", "symbol": "kr", "flag": "🇳🇴", "region": "Europe", "risk": 0.10, "rate": 10.80},
    "DK": {"name": "Denmark",           "currency": "DKK", "symbol": "kr", "flag": "🇩🇰", "region": "Europe", "risk": 0.10, "rate": 6.85},
    "FI": {"name": "Finland",           "currency": "EUR", "symbol": "€",  "flag": "🇫🇮", "region": "Europe", "risk": 0.10, "rate": 0.92},
    "PL": {"name": "Poland",            "currency": "PLN", "symbol": "zł", "flag": "🇵🇱", "region": "Europe", "risk": 0.25, "rate": 4.05},
    "AT": {"name": "Austria",           "currency": "EUR", "symbol": "€",  "flag": "🇦🇹", "region": "Europe", "risk": 0.12, "rate": 0.92},
    "PT": {"name": "Portugal",          "currency": "EUR", "symbol": "€",  "flag": "🇵🇹", "region": "Europe", "risk": 0.18, "rate": 0.92},
    "IE": {"name": "Ireland",           "currency": "EUR", "symbol": "€",  "flag": "🇮🇪", "region": "Europe", "risk": 0.12, "rate": 0.92},
    "GR": {"name": "Greece",            "currency": "EUR", "symbol": "€",  "flag": "🇬🇷", "region": "Europe", "risk": 0.30, "rate": 0.92},
    "CZ": {"name": "Czech Republic",    "currency": "CZK", "symbol": "Kč", "flag": "🇨🇿", "region": "Europe", "risk": 0.20, "rate": 23.20},
    "RO": {"name": "Romania",           "currency": "RON", "symbol": "lei","flag": "🇷🇴", "region": "Europe", "risk": 0.40, "rate": 4.55},
    "HU": {"name": "Hungary",           "currency": "HUF", "symbol": "Ft", "flag": "🇭🇺", "region": "Europe", "risk": 0.32, "rate": 360.0},
    "TR": {"name": "Turkey",            "currency": "TRY", "symbol": "₺",  "flag": "🇹🇷", "region": "Europe", "risk": 0.55, "rate": 32.50},
    "RU": {"name": "Russia",            "currency": "RUB", "symbol": "₽",  "flag": "🇷🇺", "region": "Europe", "risk": 0.85, "rate": 92.00},
    "UA": {"name": "Ukraine",           "currency": "UAH", "symbol": "₴",  "flag": "🇺🇦", "region": "Europe", "risk": 0.65, "rate": 39.50},

    # ========== ASIA ==========
    "IN": {"name": "India",             "currency": "INR", "symbol": "₹",  "flag": "🇮🇳", "region": "Asia", "risk": 0.35, "rate": 83.20},
    "CN": {"name": "China",             "currency": "CNY", "symbol": "¥",  "flag": "🇨🇳", "region": "Asia", "risk": 0.55, "rate": 7.20},
    "JP": {"name": "Japan",             "currency": "JPY", "symbol": "¥",  "flag": "🇯🇵", "region": "Asia", "risk": 0.10, "rate": 149.50},
    "KR": {"name": "South Korea",       "currency": "KRW", "symbol": "₩",  "flag": "🇰🇷", "region": "Asia", "risk": 0.18, "rate": 1330.0},
    "SG": {"name": "Singapore",         "currency": "SGD", "symbol": "S$", "flag": "🇸🇬", "region": "Asia", "risk": 0.08, "rate": 1.34},
    "HK": {"name": "Hong Kong",         "currency": "HKD", "symbol": "HK$","flag": "🇭🇰", "region": "Asia", "risk": 0.20, "rate": 7.82},
    "TH": {"name": "Thailand",          "currency": "THB", "symbol": "฿",  "flag": "🇹🇭", "region": "Asia", "risk": 0.40, "rate": 35.20},
    "MY": {"name": "Malaysia",          "currency": "MYR", "symbol": "RM", "flag": "🇲🇾", "region": "Asia", "risk": 0.30, "rate": 4.70},
    "ID": {"name": "Indonesia",         "currency": "IDR", "symbol": "Rp", "flag": "🇮🇩", "region": "Asia", "risk": 0.50, "rate": 15600.0},
    "PH": {"name": "Philippines",       "currency": "PHP", "symbol": "₱",  "flag": "🇵🇭", "region": "Asia", "risk": 0.55, "rate": 56.80},
    "VN": {"name": "Vietnam",           "currency": "VND", "symbol": "₫",  "flag": "🇻🇳", "region": "Asia", "risk": 0.50, "rate": 24500.0},
    "PK": {"name": "Pakistan",          "currency": "PKR", "symbol": "₨",  "flag": "🇵🇰", "region": "Asia", "risk": 0.70, "rate": 278.0},
    "BD": {"name": "Bangladesh",        "currency": "BDT", "symbol": "৳",  "flag": "🇧🇩", "region": "Asia", "risk": 0.60, "rate": 110.0},
    "LK": {"name": "Sri Lanka",         "currency": "LKR", "symbol": "Rs", "flag": "🇱🇰", "region": "Asia", "risk": 0.60, "rate": 320.0},
    "AE": {"name": "United Arab Emirates","currency": "AED", "symbol": "د.إ","flag": "🇦🇪", "region": "Middle East", "risk": 0.20, "rate": 3.67},
    "SA": {"name": "Saudi Arabia",      "currency": "SAR", "symbol": "﷼",  "flag": "🇸🇦", "region": "Middle East", "risk": 0.30, "rate": 3.75},
    "IL": {"name": "Israel",            "currency": "ILS", "symbol": "₪",  "flag": "🇮🇱", "region": "Middle East", "risk": 0.20, "rate": 3.70},
    "QA": {"name": "Qatar",             "currency": "QAR", "symbol": "﷼",  "flag": "🇶🇦", "region": "Middle East", "risk": 0.25, "rate": 3.64},
    "IR": {"name": "Iran",              "currency": "IRR", "symbol": "﷼",  "flag": "🇮🇷", "region": "Middle East", "risk": 0.95, "rate": 42000.0},
    "IQ": {"name": "Iraq",              "currency": "IQD", "symbol": "ع.د","flag": "🇮🇶", "region": "Middle East", "risk": 0.85, "rate": 1310.0},

    # ========== AFRICA ==========
    "NG": {"name": "Nigeria",           "currency": "NGN", "symbol": "₦",  "flag": "🇳🇬", "region": "Africa", "risk": 0.85, "rate": 1450.0},
    "ZA": {"name": "South Africa",      "currency": "ZAR", "symbol": "R",  "flag": "🇿🇦", "region": "Africa", "risk": 0.50, "rate": 18.50},
    "EG": {"name": "Egypt",             "currency": "EGP", "symbol": "£",  "flag": "🇪🇬", "region": "Africa", "risk": 0.65, "rate": 47.50},
    "KE": {"name": "Kenya",             "currency": "KES", "symbol": "KSh","flag": "🇰🇪", "region": "Africa", "risk": 0.55, "rate": 130.0},
    "MA": {"name": "Morocco",           "currency": "MAD", "symbol": "د.م","flag": "🇲🇦", "region": "Africa", "risk": 0.45, "rate": 10.10},
    "GH": {"name": "Ghana",             "currency": "GHS", "symbol": "₵",  "flag": "🇬🇭", "region": "Africa", "risk": 0.60, "rate": 15.30},

    # ========== SOUTH AMERICA ==========
    "BR": {"name": "Brazil",            "currency": "BRL", "symbol": "R$", "flag": "🇧🇷", "region": "South America", "risk": 0.45, "rate": 5.10},
    "AR": {"name": "Argentina",         "currency": "ARS", "symbol": "$",  "flag": "🇦🇷", "region": "South America", "risk": 0.65, "rate": 870.0},
    "CL": {"name": "Chile",             "currency": "CLP", "symbol": "$",  "flag": "🇨🇱", "region": "South America", "risk": 0.30, "rate": 950.0},
    "CO": {"name": "Colombia",          "currency": "COP", "symbol": "$",  "flag": "🇨🇴", "region": "South America", "risk": 0.55, "rate": 4100.0},
    "PE": {"name": "Peru",              "currency": "PEN", "symbol": "S/", "flag": "🇵🇪", "region": "South America", "risk": 0.45, "rate": 3.75},
    "VE": {"name": "Venezuela",         "currency": "VES", "symbol": "Bs", "flag": "🇻🇪", "region": "South America", "risk": 0.90, "rate": 36.50},

    # ========== OCEANIA ==========
    "AU": {"name": "Australia",         "currency": "AUD", "symbol": "A$", "flag": "🇦🇺", "region": "Oceania", "risk": 0.12, "rate": 1.52},
    "NZ": {"name": "New Zealand",       "currency": "NZD", "symbol": "NZ$","flag": "🇳🇿", "region": "Oceania", "risk": 0.10, "rate": 1.65},
}


# Risk classification thresholds
RISK_LEVELS = {
    "low":      (0.00, 0.20),
    "medium":   (0.20, 0.45),
    "high":     (0.45, 0.70),
    "critical": (0.70, 1.01),
}


# Sanctioned / high-risk countries (stricter controls applied)
SANCTIONED_COUNTRIES = {"IR", "VE", "RU"}
HIGH_RISK_COUNTRIES = {
    "NG", "RU", "CN", "PK", "BD", "IQ", "IR", "VE", "UA",
    "EG", "GH", "AR", "TR", "PH", "VN", "ID",
}


# ----------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------
def get_country(code: str) -> Optional[Dict]:
    """Get country information by ISO code."""
    return COUNTRIES.get(code.upper())


def list_countries(region: Optional[str] = None) -> List[Dict]:
    """List all countries, optionally filtered by region."""
    items = []
    for code, data in COUNTRIES.items():
        if region and data["region"] != region:
            continue
        items.append({"code": code, **data})
    return sorted(items, key=lambda x: x["name"])


def get_country_risk(code: str) -> float:
    """Get fraud risk score for a country (0.0 to 1.0)."""
    country = COUNTRIES.get(code.upper())
    return country["risk"] if country else 0.50  # default = medium risk


def get_risk_level(score: float) -> str:
    """Convert risk score to risk level string."""
    for level, (low, high) in RISK_LEVELS.items():
        if low <= score < high:
            return level
    return "critical"


def is_high_risk(code: str) -> bool:
    """Check if a country is flagged as high risk."""
    return code.upper() in HIGH_RISK_COUNTRIES


def is_sanctioned(code: str) -> bool:
    """Check if a country is on the sanctions list."""
    return code.upper() in SANCTIONED_COUNTRIES


def convert_to_usd(amount: float, currency: str) -> float:
    """Convert amount from given currency to USD (approximate)."""
    if currency == "USD":
        return amount
    for data in COUNTRIES.values():
        if data["currency"] == currency:
            return round(amount / data["rate"], 2)
    return amount  # unknown currency, assume USD


def convert_from_usd(amount_usd: float, target_currency: str) -> float:
    """Convert USD amount to target currency."""
    if target_currency == "USD":
        return amount_usd
    for data in COUNTRIES.values():
        if data["currency"] == target_currency:
            return round(amount_usd * data["rate"], 2)
    return amount_usd


def format_amount(amount: float, code: str) -> str:
    """Format an amount with the country's currency symbol."""
    country = COUNTRIES.get(code.upper())
    if not country:
        return f"${amount:,.2f}"
    return f"{country['symbol']}{amount:,.2f}"


def get_regions() -> List[str]:
    """Get list of all unique regions."""
    return sorted(set(c["region"] for c in COUNTRIES.values()))


def get_country_codes() -> List[str]:
    """Get all ISO country codes."""
    return sorted(COUNTRIES.keys())


# Backwards compatibility with old data_loader
COUNTRY_CODES = list(COUNTRIES.keys())
