"""Pydantic model for a structured receipt transaction."""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class LineItem(BaseModel):
    """A single line item on a receipt."""
    description: str = ""
    quantity: float = 1
    unit_price: float = 0.0
    total: float = 0.0


class Transaction(BaseModel):
    """Structured receipt data — output of the extraction + validation pipeline."""

    # ── Core fields ──────────────────────────────────────────────────
    date: str = Field(default="", description="YYYY-MM-DD")
    merchant: str = ""
    currency: str = Field(default="ZAR")
    total: float = Field(default=0.0)
    vat: Optional[float] = None
    category: str = Field(default="Unknown")
    receipt_number: str = ""
    payment_method: str = ""  # Card / Cash / EFT / Unknown
    business_use: str = Field(default="Unknown")  # Business / Personal / Unknown
    items: list[LineItem] = Field(default_factory=list)

    # ── Quality / review ─────────────────────────────────────────────
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    needs_review: bool = True
    warnings: list[str] = Field(default_factory=list)

    # ── Evidence pointers ────────────────────────────────────────────
    image_path: str = ""
    raw_text_path: str = ""
    telegram_file_id: str = ""
    telegram_message_id: int = 0

    # ── Routing flags ────────────────────────────────────────────────
    foreign_currency: bool = False

    def preview(self) -> str:
        """Format a human-readable Telegram preview message."""
        lines = [
            "📋 *Receipt Preview*",
            f"📅 Date: `{self.date or '???'}`",
            f"🏪 Merchant: `{self.merchant or '???'}`",
            f"💰 Total: `{self.currency} {self.total:.2f}`",
        ]
        if self.vat is not None:
            lines.append(f"🧾 VAT: `{self.currency} {self.vat:.2f}`")
        lines += [
            f"📂 Category: `{self.category}`",
            f"💳 Payment: `{self.payment_method or '???'}`",
            f"🏢 Use: `{self.business_use}`",
            f"🔒 Confidence: `{self.confidence:.0%}`",
        ]
        if self.items:
            lines.append("\n📦 *Items:*")
            for item in self.items[:10]:  # cap at 10
                lines.append(f"  • {item.description}: {self.currency} {item.total:.2f}")
        if self.warnings:
            lines.append("\n⚠️ *Warnings:*")
            for w in self.warnings:
                lines.append(f"  ⚠ {w}")
        return "\n".join(lines)
