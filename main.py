"""Receipt → Bookkeeping → Excel  |  Telegram Bot Entry Point.

Pipeline:
  photo → intake → OCR → LLM structuring → validate → categorize
       → confirm (human-in-the-loop) → Excel writer → audit log

Usage:
  1. Fill in .env with your TELEGRAM_BOT_TOKEN
  2. Ensure LM Studio is running with Qwen3 VL loaded
  3. python main.py
"""

from __future__ import annotations

import logging
import sys

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import config
from agents.intake import handle_intake
from agents.ocr_extract import extract_text
from agents.llm_structurer import structure_receipt
from agents.validator import validate
from agents.categorizer import categorize
from agents.confirm import send_preview, handle_callback, apply_edits, CONFIRM, EDIT, REJECT
from agents.excel_writer import append_transaction
from agents.audit import run_full_audit, monthly_summary

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")

# ── Per-chat state (in-memory) ───────────────────────────────────────
# Maps chat_id → the Transaction currently waiting for confirmation/edit
_pending: dict[int, dict] = {}


# ── Pipeline handler ─────────────────────────────────────────────────

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main pipeline: triggered when a user sends a photo or image document."""
    message = update.effective_message
    if message is None:
        return

    chat_id = message.chat_id
    await message.reply_text("📥 Got it! Processing your receipt…")

    # ── Step 1: Intake ───────────────────────────────────────────────
    intake = await handle_intake(update, context)
    if intake is None:
        return  # error already replied

    # ── Step 2: OCR ──────────────────────────────────────────────────
    await message.reply_text("🔍 Extracting text…")
    raw_text, raw_text_path, quality = extract_text(intake.image_path)

    if quality == "bad" and not raw_text:
        await message.reply_text(
            "⚠️ Could not read any text from this image.\n"
            "I'll try the vision model directly…"
        )

    # ── Step 3: LLM structuring ──────────────────────────────────────
    await message.reply_text("🧠 Analyzing receipt…")
    txn = structure_receipt(
        raw_text=raw_text,
        caption=intake.caption,
        image_path=intake.image_path,
        extraction_quality=quality,
    )

    # Attach evidence pointers
    txn.image_path = intake.image_path
    txn.raw_text_path = raw_text_path
    txn.telegram_file_id = intake.file_id
    txn.telegram_message_id = intake.message_id

    # ── Step 4: Validate ─────────────────────────────────────────────
    txn = validate(txn)

    # ── Step 5: Categorize ───────────────────────────────────────────
    txn = categorize(txn, raw_text=raw_text, caption=intake.caption)

    # ── Step 6: Send preview + store pending ─────────────────────────
    _pending[chat_id] = {
        "txn": txn,
        "raw_text": raw_text,
        "caption": intake.caption,
    }
    await send_preview(chat_id, txn, context)


# ── Callback handler (button presses) ───────────────────────────────

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ✅/✏️/❌ button presses on the preview message."""
    query = update.callback_query
    if query is None:
        return

    chat_id = query.message.chat_id if query.message else 0
    action = await handle_callback(update, context)

    pending = _pending.get(chat_id)
    if pending is None:
        if query.message:
            await query.message.reply_text("❌ No pending transaction found. Send a new receipt.")
        return

    txn = pending["txn"]

    if action == "confirm":
        result = append_transaction(txn)
        if query.message:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ *Saved!*\n{result}",
                parse_mode="Markdown",
            )
        _pending.pop(chat_id, None)

    elif action == "edit":
        # Stay in pending state — next text message is the edit
        _pending[chat_id]["awaiting_edit"] = True

    elif action == "reject":
        append_transaction(txn, rejected=True)
        _pending.pop(chat_id, None)


# ── Text handler (for edit replies) ──────────────────────────────────

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle free-text messages — either edit replies or random text."""
    message = update.effective_message
    if message is None or not message.text:
        return

    chat_id = message.chat_id
    pending = _pending.get(chat_id)

    if pending and pending.get("awaiting_edit"):
        # Apply edits
        txn = apply_edits(pending["txn"], message.text)
        pending["txn"] = txn
        pending["awaiting_edit"] = False

        # Show updated preview
        await send_preview(chat_id, txn, context)
    else:
        await message.reply_text(
            "📸 Send me a *photo* of a receipt and I'll extract, categorize, "
            "and log it to Excel for you!\n\n"
            "Commands:\n"
            "/audit — Run an audit report\n"
            "/summary — Monthly spending summary\n"
            "/help — Show this message",
            parse_mode="Markdown",
        )


# ── Command handlers ─────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start and /help."""
    await update.effective_message.reply_text(
        "🧾 *Receipt Bookkeeper Bot*\n\n"
        "Send me a photo of a receipt and I'll:\n"
        "1. Extract the text (OCR)\n"
        "2. Structure the data (AI)\n"
        "3. Validate & categorize\n"
        "4. Ask you to confirm\n"
        "5. Save to Excel\n\n"
        "Commands:\n"
        "/audit — Full audit report\n"
        "/summary — Monthly spending summary\n"
        "/help — This message",
        parse_mode="Markdown",
    )


async def cmd_audit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /audit command."""
    await update.effective_message.reply_text("🔍 Running audit…")
    report = run_full_audit()
    await update.effective_message.reply_text(report, parse_mode="Markdown")


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /summary command."""
    report = monthly_summary()
    await update.effective_message.reply_text(report, parse_mode="Markdown")


# ── Main ─────────────────────────────────────────────────────────────

def main() -> None:
    """Wire up all handlers and start the Telegram bot."""
    if not config.BOT_TOKEN or config.BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ ERROR: Set TELEGRAM_BOT_TOKEN in .env first!")
        print("   1. Message @BotFather on Telegram")
        print("   2. Send /newbot and follow the prompts")
        print("   3. Copy the token into .env")
        sys.exit(1)

    app = Application.builder().token(config.BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("audit", cmd_audit))
    app.add_handler(CommandHandler("summary", cmd_summary))

    # Photos and image documents
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(
        filters.Document.IMAGE,
        on_photo,
    ))

    # Inline keyboard callbacks
    app.add_handler(CallbackQueryHandler(on_callback))

    # Free text (edit replies + fallback)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    logger.info("🚀 Bot starting — polling for messages…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
