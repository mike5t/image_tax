"""Agent 6: Telegram Confirmation UI (Human-in-the-Loop).

Sends a preview of the extracted transaction to the user with inline
buttons for Confirm / Edit / Reject.
"""

from __future__ import annotations

import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from models.transaction import Transaction
from agents import validator

logger = logging.getLogger(__name__)

# Callback data prefixes
CONFIRM = "txn_confirm"
EDIT = "txn_edit"
REJECT = "txn_reject"


def _build_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm", callback_data=CONFIRM),
            InlineKeyboardButton("✏️ Edit", callback_data=EDIT),
            InlineKeyboardButton("❌ Reject", callback_data=REJECT),
        ]
    ])


async def send_preview(
    chat_id: int,
    txn: Transaction,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Send transaction preview with action buttons."""
    text = txn.preview()

    if txn.needs_review:
        text += "\n\n🔍 *This transaction needs your review.*"
        if txn.warnings:
            text += "\nPlease check the warnings above."

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=_build_keyboard(),
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Handle inline button press.  Returns the action taken: 'confirm', 'edit', 'reject'."""
    query = update.callback_query
    if query is None:
        return "unknown"
    await query.answer()

    data = query.data
    if data == CONFIRM:
        await query.edit_message_text("✅ *Confirmed!* Writing to Excel…", parse_mode="Markdown")
        return "confirm"
    elif data == EDIT:
        await query.edit_message_text(
            "✏️ *Edit mode.*\n\n"
            "Reply with the fields to change, e.g.:\n"
            "`total=245.50 category=Groceries business=Personal`",
            parse_mode="Markdown",
        )
        return "edit"
    elif data == REJECT:
        await query.edit_message_text("❌ *Rejected.* This receipt will not be recorded.", parse_mode="Markdown")
        return "reject"

    return "unknown"


def apply_edits(txn: Transaction, edit_text: str) -> Transaction:
    """Parse user edits (key=value pairs) and merge into the transaction.

    Supported keys: total, category, business, currency, date, merchant, payment, vat
    """
    # Parse key=value pairs
    pairs = re.findall(r"(\w+)\s*=\s*(\S+)", edit_text)
    for key, value in pairs:
        key = key.lower()
        if key == "total":
            try:
                txn.total = float(value)
            except ValueError:
                txn.warnings.append(f"Could not parse total '{value}'")
        elif key == "category":
            txn.category = value
        elif key in ("business", "business_use"):
            txn.business_use = value
        elif key == "currency":
            txn.currency = value.upper()
        elif key == "date":
            txn.date = value
        elif key == "merchant":
            txn.merchant = value
        elif key in ("payment", "payment_method"):
            txn.payment_method = value
        elif key == "vat":
            try:
                txn.vat = float(value)
            except ValueError:
                txn.warnings.append(f"Could not parse vat '{value}'")

    # Re-validate after edits
    txn.needs_review = False  # Reset — validator will re-set if needed
    txn.warnings = []
    txn = validator.validate(txn)
    return txn
