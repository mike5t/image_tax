---
description: How to run the Receipt Bookkeeper Bot pipeline
---

# Receipt → Bookkeeping → Excel Pipeline

## Prerequisites

1. **LM Studio** running with `qwen/qwen3-vl-8b` loaded at `http://127.0.0.1:1234`
2. **Telegram Bot Token** set in `.env` (get it from @BotFather)
3. Python dependencies installed: `pip install -r requirements.txt`
4. (Optional) Tesseract OCR installed and path set in `.env`

## Steps

// turbo-all

1. Install dependencies
```bash
pip install -r requirements.txt
```

2. Run the bot
```bash
python main.py
```

3. Send a receipt photo to your bot on Telegram

4. The bot will:
   - Download and store the image (`receipts/YYYY-MM/`)
   - Extract text via OCR (Tesseract) or Vision LLM (Qwen3 VL)
   - Structure the data into JSON via LLM
   - Validate totals, dates, currencies
   - Categorize using SA-friendly keyword rules
   - Send a preview with ✅ Confirm / ✏️ Edit / ❌ Reject buttons
   - On confirm → append to `Transactions.xlsx`

## Editing a Transaction

After pressing ✏️ Edit, reply with key=value pairs:
```
total=245.50 category=Groceries business=Personal
```

## Audit & Summary

- `/audit` — Runs duplicate detection, missing evidence, anomaly flags, and monthly summary
- `/summary` — Current month spending by category

## Pipeline Nodes (for reference)

1. `telegram_intake` — Download photo, save evidence
2. `download_and_store_evidence` — Create `receipts/YYYY-MM/` path
3. `ocr_extract_text` — Tesseract + VL fallback
4. `llm_extract_json` — Qwen3 VL → strict JSON
5. `validate_normalize` — Date, currency, total checks
6. `categorize_route` — Keyword rules + foreign currency routing
7. `send_preview_confirm` — Telegram preview with buttons
8. `handle_edit_or_confirm` — Process user decision
9. `append_excel` — Write to Transactions.xlsx (master + category sheets)
10. `log_audit_trail` — Evidence paths stored in every row
