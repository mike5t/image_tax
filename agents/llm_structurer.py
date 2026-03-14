"""Agent 3: LLM Structuring via LM Studio.

Sends raw OCR text (+ optionally the image) to Qwen3 VL and asks for a
strict JSON transaction object.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path

from openai import OpenAI

import config
from models.transaction import Transaction

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an expert receipt-reading assistant. Given a receipt image and/or OCR text, \
extract a single JSON object with EXACTLY these fields:

{
  "date": "YYYY-MM-DD or empty string",
  "merchant": "store/company name or empty string",
  "currency": "ZAR, USD, EUR, or GBP",
  "total": 0.00,
  "vat": null or number,
  "category": "one of: Rent, Groceries, Transport, Airtime/Data, Fuel, Health/Pharmacy, Utilities, Insurance, Office Supplies, Software/Subscriptions, Entertainment, Food/Dining, Unknown",
  "receipt_number": "string or empty",
  "payment_method": "Card, Cash, EFT, or Unknown",
  "business_use": "Business, Personal, or Unknown",
  "items": [{"description": "item name", "quantity": 1, "unit_price": 0.00, "total": 0.00}],
  "confidence": 0.0 to 1.0,
  "needs_review": true or false
}

CRITICAL RULES:
- You MUST extract EVERY individual line item from the receipt into the "items" array.
- Each product/service on the receipt must be its own entry in "items" with its description, quantity, unit_price, and total.
- Do NOT skip any items. Even if there are 50 items, list them ALL.
- The "total" field at the top level should be the receipt grand total.
- If the total or date cannot be determined clearly, set needs_review=true and confidence below 0.6.
- For South African receipts, default currency to "ZAR".
- If you see "$" or "USD", set currency to "USD".
- Do NOT guess amounts — if unclear, set total=0 and needs_review=true.
- Return ONLY valid JSON, no markdown fences, no explanation.
"""


def _extract_json(text: str) -> dict | None:
    """Try to parse JSON from the LLM response, handling markdown fences and truncation."""
    # Strip markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)

    # Strip repetitive item blocks BEFORE parsing
    # The VL model often repeats the same item entry dozens of times
    cleaned = _collapse_repeated_json_items(cleaned)

    # Try parsing as-is first
    result = _try_json_parse(cleaned)
    if result:
        return result

    # If that fails, the JSON is likely truncated — try to close it
    for suffix in ['}]}', '"}]}', '0}]}', ']}'  , '}']:
        result = _try_json_parse(cleaned + suffix)
        if result:
            logger.info("Fixed truncated JSON by appending: %s", suffix)
            return result

    # Last resort: find the largest valid JSON substring
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        result = _try_json_parse(match.group())
        if result:
            return result

    return None


def _try_json_parse(text: str) -> dict | None:
    """Attempt JSON parse, return dict or None."""
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def _collapse_repeated_json_items(text: str) -> str:
    """Detect and remove repeated identical JSON item objects.

    Qwen3 VL tends to repeat the same item entry dozens of times.
    This keeps only unique items (by their full JSON text).
    """
    # Find the items array region
    items_match = re.search(r'"items"\s*:\s*\[', text)
    if not items_match:
        return text

    start = items_match.end()

    # Extract individual item objects
    item_pattern = re.compile(r'\{[^{}]+\}')
    items_found = item_pattern.findall(text[start:])

    if len(items_found) <= 3:
        return text  # Not enough to have a repetition problem

    # Keep only unique items (preserve order)
    seen = set()
    unique_items = []
    for item_str in items_found:
        # Normalize whitespace for comparison
        normalized = re.sub(r'\s+', ' ', item_str.strip())
        if normalized not in seen:
            seen.add(normalized)
            unique_items.append(item_str)

    if len(unique_items) == len(items_found):
        return text  # No duplicates found

    logger.info("Collapsed %d repeated items → %d unique", len(items_found), len(unique_items))

    # Rebuild the items array
    new_items = ",\n    ".join(unique_items)
    # Replace from items array start to end of text (since it may be truncated)
    before = text[:start]
    after_items = f"\n    {new_items}\n  ]"

    # Try to find what comes after the items array
    # Find matching closing bracket for the items array
    bracket_depth = 1
    pos = start
    while pos < len(text) and bracket_depth > 0:
        if text[pos] == '[':
            bracket_depth += 1
        elif text[pos] == ']':
            bracket_depth -= 1
        pos += 1

    if bracket_depth == 0:
        # Found the closing bracket — keep everything after it
        remaining = text[pos:]
        return before + f"\n    {new_items}\n  ]" + remaining
    else:
        # Array was truncated — close it and the parent object
        return before + f"\n    {new_items}\n  ],\n  \"confidence\": 0.7,\n  \"needs_review\": true\n}}"


def structure_receipt(
    raw_text: str,
    caption: str = "",
    image_path: str = "",
    extraction_quality: str = "good",
) -> Transaction:
    """Send OCR text to LM Studio and get back a structured Transaction.

    If extraction_quality is "bad", also sends the image for vision analysis.
    """
    client = OpenAI(base_url=f"{config.LM_STUDIO_URL}/v1", api_key="lm-studio")

    # Build user message — ALWAYS include the image for best accuracy
    user_parts: list[dict] = []

    if image_path:
        try:
            with open(image_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            ext = Path(image_path).suffix.lower().lstrip(".")
            mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                    "webp": "image/webp"}.get(ext, "image/jpeg")
            user_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            })
        except Exception as exc:
            logger.warning("Could not attach image: %s", exc)

    # Compose text prompt — include OCR text as a hint
    prompt_text = ""
    if raw_text.strip():
        # Truncate OCR text to avoid overwhelming the model
        truncated = raw_text[:1500]
        prompt_text += f"OCR text (may contain errors):\n{truncated}\n\n"
    if caption:
        prompt_text += f"User note: {caption}\n\n"
    prompt_text += (
        "Look at the receipt image carefully and extract the JSON transaction object. "
        "You MUST list EVERY individual item with its price in the 'items' array. "
        "The OCR text above may be incomplete — always read directly from the image."
    )

    user_parts.append({"type": "text", "text": prompt_text})

    try:
        resp = client.chat.completions.create(
            model=config.LM_STUDIO_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_parts},
            ],
            temperature=0.1,
            max_tokens=2048,
        )
        content = resp.choices[0].message.content or ""
        logger.info("LLM raw response length: %d chars", len(content))
        logger.info("LLM raw response (first 500): %s", content[:500])

        # Save debug response next to the image
        if image_path:
            debug_path = Path(image_path).with_suffix(".llm_response.txt")
            debug_path.write_text(content, encoding="utf-8")
            logger.info("Saved LLM debug response to: %s", debug_path)

    except Exception as exc:
        logger.error("LLM structuring failed: %s", exc)
        return Transaction(needs_review=True, warnings=["LLM call failed"], confidence=0.0)

    # Parse
    data = _extract_json(content)
    if data is None:
        logger.error("Could not parse JSON from LLM response: %s", content[:300])
        return Transaction(needs_review=True, warnings=["JSON parse failed"], confidence=0.0)

    # Log parsed items count
    items_raw = data.get("items", [])
    logger.info("Parsed JSON — items count: %d, total: %s", len(items_raw) if isinstance(items_raw, list) else 0, data.get("total"))

    # Build Transaction — use .get() with defaults so missing keys don't crash
    try:
        txn = Transaction(
            date=str(data.get("date", "")),
            merchant=str(data.get("merchant", "")),
            currency=str(data.get("currency", "ZAR")),
            total=float(data.get("total", 0)),
            vat=data.get("vat"),
            category=str(data.get("category", "Unknown")),
            receipt_number=str(data.get("receipt_number", "")),
            payment_method=str(data.get("payment_method", "Unknown")),
            business_use=str(data.get("business_use", "Unknown")),
            confidence=float(data.get("confidence", 0.5)),
            needs_review=bool(data.get("needs_review", True)),
        )
        # Parse items if present
        if isinstance(items_raw, list):
            from models.transaction import LineItem
            for item in items_raw:
                if isinstance(item, dict):
                    txn.items.append(LineItem(
                        description=str(item.get("description", "")),
                        quantity=float(item.get("quantity", 1)),
                        unit_price=float(item.get("unit_price", 0)),
                        total=float(item.get("total", 0)),
                    ))
        logger.info("Built Transaction with %d items", len(txn.items))
    except Exception as exc:
        logger.error("Error building Transaction from LLM data: %s", exc)
        return Transaction(needs_review=True, warnings=[f"Parse error: {exc}"], confidence=0.0)

    return txn
