"""Agent 4: Validator + Normalizer.

Catches common errors before data reaches Excel.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

import config
from models.transaction import Transaction

logger = logging.getLogger(__name__)

# Date patterns we try to parse
_DATE_FORMATS = [
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%Y%m%d",
]


def _normalize_date(raw: str) -> tuple[str, bool]:
    """Try to parse raw date string into YYYY-MM-DD.

    Returns (normalized_date, success).
    """
    if not raw:
        return "", False
    raw = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%Y-%m-%d"), True
        except ValueError:
            continue
    # Already in correct format?
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw, True
    return raw, False


def validate(txn: Transaction) -> Transaction:
    """Validate and normalize a Transaction in-place.  Returns the same object."""
    warnings: list[str] = list(txn.warnings)

    # ── Total ────────────────────────────────────────────────────────
    if txn.total <= 0:
        warnings.append("Total is zero or negative.")
        txn.needs_review = True

    # ── Currency ─────────────────────────────────────────────────────
    upper_cur = txn.currency.upper().strip()
    if upper_cur not in config.ALLOWED_CURRENCIES:
        warnings.append(f"Unrecognized currency '{txn.currency}'. Defaulting to ZAR.")
        upper_cur = "ZAR"
        txn.needs_review = True
    txn.currency = upper_cur

    # ── Date ─────────────────────────────────────────────────────────
    norm_date, ok = _normalize_date(txn.date)
    if not ok and txn.date:
        warnings.append(f"Could not parse date '{txn.date}'.")
        txn.needs_review = True
    txn.date = norm_date

    # ── Category ─────────────────────────────────────────────────────
    if txn.category not in config.ALLOWED_CATEGORIES:
        warnings.append(f"Unrecognized category '{txn.category}'. Setting to Unknown.")
        txn.category = "Unknown"
        txn.needs_review = True

    # ── VAT sanity ───────────────────────────────────────────────────
    if txn.vat is not None and txn.total > 0:
        if txn.vat > txn.total:
            warnings.append("VAT exceeds total — possible subtotal/total mix-up.")
            txn.needs_review = True

    # ── Items vs total check ─────────────────────────────────────────
    if txn.items:
        items_sum = sum(item.total for item in txn.items)
        if items_sum > 0 and abs(items_sum - txn.total) > 1.0:
            warnings.append(
                f"Items sum ({items_sum:.2f}) differs from total ({txn.total:.2f})."
            )
            txn.needs_review = True

    # ── Confidence gate ──────────────────────────────────────────────
    if txn.confidence < 0.6:
        txn.needs_review = True

    # ── Foreign currency flag ────────────────────────────────────────
    if txn.currency != "ZAR":
        txn.foreign_currency = True

    txn.warnings = warnings
    return txn
