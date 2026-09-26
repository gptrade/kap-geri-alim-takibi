"""Minimal Telegram sender. Without env vars, messages just go to stdout."""
from __future__ import annotations

import os
import logging

import requests

log = logging.getLogger("telegram_notify")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def send(text: str) -> None:
    if not TOKEN or not CHAT_ID:
        print(text)
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            log.warning("Telegram send failed: %s %s", resp.status_code, resp.text)
    except requests.RequestException as exc:
        log.warning("Telegram send failed: %s", exc)


def format_buyback_message(row: dict) -> str:
    company = row.get("company_title") or "?"
    tickers = row.get("tickers") or "?"
    tx_date = row.get("transaction_date") or "-"
    qty = row.get("quantity")
    qty_s = f"{qty:,.0f}".replace(",", ".") if qty is not None else "-"
    price = row.get("price")
    price_low, price_high = row.get("price_low"), row.get("price_high")
    if price is not None:
        price_s = f"{price:.2f} TL".replace(".", ",")
    elif price_low is not None and price_high is not None:
        price_s = f"{price_low:.2f}-{price_high:.2f} TL".replace(".", ",")
    else:
        price_s = "-"
    pct = row.get("ownership_pct_after")
    pct_s = f"%{pct:.2f}".replace(".", ",") if pct is not None else "-"
    review_note = "\n⚠️ Otomatik ayrıştırma eksik kaldı, bildirimi kontrol et." if row.get("needs_review") else ""

    return (
        f"🏢 <b>{company}</b> ({tickers})\n"
        f"Kendi payını geri aldı\n"
        f"İşlem tarihi: {tx_date}\n"
        f"Adet: {qty_s}\n"
        f"Fiyat: {price_s}\n"
        f"Geri alım sonrası sermaye payı: {pct_s}\n"
        f"Kaynak: {row.get('source_url')}"
        f"{review_note}"
    )
