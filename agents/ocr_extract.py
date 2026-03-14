"""Agent 2: OCR Extraction.

Primary path: Tesseract OCR (fast, local).
Fallback: Qwen3 VL via LM Studio (vision endpoint).
"""

from __future__ import annotations

import base64
import logging
import re
from pathlib import Path

from openai import OpenAI

import config

logger = logging.getLogger(__name__)

# Quality thresholds
_MIN_TEXT_LEN = 20  # below this → bad quality


def _try_tesseract(image_path: str) -> str | None:
    """Attempt Tesseract OCR.  Returns raw text or None."""
    if not config.TESSERACT_PATH:
        return None
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_PATH
        from PIL import Image
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img)
        return text.strip() if text.strip() else None
    except Exception as exc:
        logger.warning("Tesseract failed: %s", exc)
        return None


def _try_vision_llm(image_path: str) -> str | None:
    """Send image to Qwen3 VL via LM Studio and ask it to read all text."""
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()

        # Determine mime type
        ext = Path(image_path).suffix.lower()
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "webp": "image/webp", "gif": "image/gif"}.get(ext.lstrip("."), "image/jpeg")

        client = OpenAI(base_url=f"{config.LM_STUDIO_URL}/v1", api_key="lm-studio")
        resp = client.chat.completions.create(
            model=config.LM_STUDIO_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        },
                        {
                            "type": "text",
                            "text": (
                                "Read ALL text from this receipt image exactly as printed. "
                                "Include every line, number, date, and amount. "
                                "Do not summarize or interpret — just transcribe."
                            ),
                        },
                    ],
                }
            ],
            temperature=0.1,
            max_tokens=1500,  # Enough to capture full receipt text
        )
        text = resp.choices[0].message.content or ""
        text = _clean_repetition(text.strip())
        return text if text else None
    except Exception as exc:
        logger.error("Vision LLM extraction failed: %s", exc)
        return None


def _clean_repetition(text: str) -> str:
    """Detect and remove repetitive patterns from VL model output."""
    if not text:
        return text

    # Truncate to max 2000 chars
    text = text[:2000]

    # Detect repeated lines: if the same line appears > 5 times, collapse
    lines = text.split("\n")
    cleaned: list[str] = []
    prev_line = None
    repeat_count = 0
    for line in lines:
        stripped = line.strip()
        if stripped == prev_line:
            repeat_count += 1
            if repeat_count <= 2:  # allow up to 2 repeats
                cleaned.append(line)
        else:
            repeat_count = 0
            cleaned.append(line)
        prev_line = stripped

    result = "\n".join(cleaned)

    # Detect repeated character sequences (e.g., "000000000...")
    result = re.sub(r"(.)\1{20,}", r"\1\1\1", result)

    return result.strip()


def extract_text(image_path: str) -> tuple[str, str, str]:
    """Run OCR on the receipt image.

    Returns:
        (raw_text, raw_text_path, extraction_quality)
        extraction_quality is one of: "good", "medium", "bad"
    """
    raw_text: str = ""
    source = "none"

    # 1. Try Tesseract
    tess_text = _try_tesseract(image_path)
    if tess_text and len(tess_text) >= _MIN_TEXT_LEN:
        raw_text = tess_text
        source = "tesseract"
    else:
        # 2. Fallback to vision LLM
        vl_text = _try_vision_llm(image_path)
        if vl_text:
            raw_text = vl_text
            source = "vision_llm"

    # Determine quality
    # Also check if text looks repetitive (sign of VL hallucination)
    unique_lines = set(raw_text.split("\n"))
    repetition_ratio = len(unique_lines) / max(len(raw_text.split("\n")), 1)

    if len(raw_text) >= 100 and repetition_ratio > 0.3:
        quality = "good"
    elif len(raw_text) >= _MIN_TEXT_LEN and repetition_ratio > 0.2:
        quality = "medium"
    else:
        quality = "bad"

    # Save raw text alongside the image
    txt_path = Path(image_path).with_suffix(".txt")
    txt_path.write_text(raw_text, encoding="utf-8")

    logger.info("OCR [%s] quality=%s  len=%d  → %s", source, quality, len(raw_text), txt_path)
    return raw_text, str(txt_path), quality


def test_lm_studio():
    """Quick connectivity test — call from CLI."""
    client = OpenAI(base_url=f"{config.LM_STUDIO_URL}/v1", api_key="lm-studio")
    models = client.models.list()
    print("✅ LM Studio reachable. Models:", [m.id for m in models.data])
