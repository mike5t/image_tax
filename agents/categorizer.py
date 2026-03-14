"""Agent 5: Rules-based Categorizer (SA bookkeeping friendly).

Runs AFTER LLM extraction so it can override or confirm the LLM's category
using deterministic keyword rules.
"""

from __future__ import annotations

import logging
import re

from models.transaction import Transaction

logger = logging.getLogger(__name__)

# Each rule: (compiled regex, category)
# Patterns are case-insensitive and checked against merchant + raw_text + caption
_RULES: list[tuple[re.Pattern, str]] = [
    # Rent
    (re.compile(r"\b(rent|lease|landlord|rental|tenant)\b", re.I), "Rent"),
    # Groceries
    (re.compile(
        r"\b(shoprite|checkers|pick\s*n\s*pay|pnp|woolworths|spar|food\s*lover|"
        r"makro|game|boxer|usave|cambridge\s*food)\b", re.I
    ), "Groceries"),
    # Transport
    (re.compile(r"\b(uber|bolt|taxi|lyft|e-?hailing|gautrain|metrorail)\b", re.I), "Transport"),
    # Airtime / Data
    (re.compile(
        r"\b(vodacom|mtn|telkom|cell\s*c|rain\s+mobile|airtime|data\s*bundle|"
        r"prepaid\s*(airtime|data))\b", re.I
    ), "Airtime/Data"),
    # Fuel
    (re.compile(
        r"\b(engen|shell|sasol|caltex|bp|total\s*energies|fuel|petrol|diesel|"
        r"unleaded)\b", re.I
    ), "Fuel"),
    # Health / Pharmacy
    (re.compile(r"\b(clicks|dis-?chem|pharmacy|medical|doctor|dr\b|pathcare)\b", re.I), "Health/Pharmacy"),
    # Utilities
    (re.compile(
        r"\b(electricity|eskom|prepaid\s*electricity|water\s*bill|municipal|"
        r"rates\s*&?\s*taxes|city\s*power)\b", re.I
    ), "Utilities"),
    # Insurance
    (re.compile(r"\b(insurance|old\s*mutual|sanlam|discovery|momentum|hollard)\b", re.I), "Insurance"),
    # Software / Subscriptions
    (re.compile(
        r"\b(subscription|netflix|spotify|google\s*(one|storage)|microsoft|"
        r"adobe|github|openai)\b", re.I
    ), "Software/Subscriptions"),
    # Food / Dining
    (re.compile(
        r"\b(restaurant|kfc|mcdonalds|nandos|steers|wimpy|spur|ocean\s*basket|"
        r"debonairs|romans|pizza)\b", re.I
    ), "Food/Dining"),
    # Entertainment
    (re.compile(r"\b(ster-?kinekor|cinema|nu\s*metro|concert|ticket)\b", re.I), "Entertainment"),
]


def categorize(txn: Transaction, raw_text: str = "", caption: str = "") -> Transaction:
    """Apply keyword rules to set / override the transaction category.

    If no rule matches AND the LLM already set a valid category, keep the LLM's.
    If no rule matches and category is still Unknown, mark for review.
    """
    # Build a single searchable blob
    blob = f"{txn.merchant} {raw_text} {caption}".lower()

    matched_category: str | None = None
    for pattern, category in _RULES:
        if pattern.search(blob):
            matched_category = category
            break

    if matched_category:
        if txn.category != matched_category:
            logger.info("Category override: %s → %s", txn.category, matched_category)
        txn.category = matched_category
    elif txn.category == "Unknown":
        txn.needs_review = True
        if "Unknown category" not in txn.warnings:
            txn.warnings.append("Unknown category — please confirm.")

    # Foreign currency routing
    if txn.currency != "ZAR":
        txn.foreign_currency = True

    return txn
