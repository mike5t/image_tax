"""Agent 1: Telegram Intake + Evidence Storage.

Downloads receipt images from Telegram and saves them with audit-friendly
filenames in a date-partitioned directory structure.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass

from telegram import Update
from telegram.ext import ContextTypes

import config

logger = logging.getLogger(__name__)


@dataclass
class IntakeResult:
    """Data captured from a single Telegram message."""
    image_path: str
    caption: str
    chat_id: int
    message_id: int
    file_id: str
    sender_id: int


async def handle_intake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> IntakeResult | None:
    """Download the largest available photo/document and store it as evidence.

    Returns an IntakeResult on success, or None after replying with an error.
    """
    message = update.effective_message
    if message is None:
        return None

    chat_id = message.chat_id
    message_id = message.message_id
    sender_id = message.from_user.id if message.from_user else 0
    caption = message.caption or ""

    # Determine the file to download
    if message.photo:
        # Telegram sends multiple sizes; pick the largest
        file_id = message.photo[-1].file_id
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        file_id = message.document.file_id
    else:
        await message.reply_text(
            "📸 Please send a *photo* of the slip/receipt (or an image file).",
            parse_mode="Markdown",
        )
        return None

    # Build evidence path:  receipts/2026-02/2026-02-17_10-22-31_<msg_id>.jpg
    now = datetime.now()
    month_dir = config.RECEIPTS_DIR / now.strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{now.strftime('%Y-%m-%d_%H-%M-%S')}_{message_id}.jpg"
    image_path = month_dir / filename

    # Download
    try:
        tg_file = await context.bot.get_file(file_id)
        await tg_file.download_to_drive(str(image_path))
        logger.info("Saved evidence: %s", image_path)
    except Exception as exc:
        logger.error("Failed to download image: %s", exc)
        await message.reply_text("❌ Failed to download the image. Please try again.")
        return None

    return IntakeResult(
        image_path=str(image_path),
        caption=caption,
        chat_id=chat_id,
        message_id=message_id,
        file_id=file_id,
        sender_id=sender_id,
    )
