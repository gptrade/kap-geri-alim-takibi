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


def _tr_num(n, decimals=0):
    if n is None:
        return "-"
    return f"{n:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _tr_pct(n, decimals=4):
    if n is None:
        return "-"
    return "%" + _tr_num(n, decimals)


def format_buyback_message(row: dict) -> str:
    company = row.get("company_title") or "?"
    tickers = row.get("tickers") or "?"
    tx_date = row.get("transaction_date") or "-"
    qty_s = _tr_num(row.get("quantity"))
    price = row.get("price")
    price_low, price_high = row.get("price_low"), row.get("price_high")
    if price is not None:
        price_s = f"{_tr_num(price, 3)} TL"
    elif price_low is not None and price_high is not None:
        price_s = f"{_tr_num(price_low, 3)}-{_tr_num(price_high, 3)} TL"
    else:
        price_s = "-"
    total_held_s = _tr_num(row.get("total_held_after"))
    total_pct_s = _tr_pct(row.get("ownership_pct_after"))
    review_note = "\n⚠️ Otomatik ayrıştırma eksik kaldı, bildirimi kontrol et." if row.get("needs_review") else ""

    return (
        f"🏢 <b>{company}</b> ({tickers})\n"
        f"Kendi payını geri aldı\n"
        f"Son işlem tarihi: {tx_date}\n"
        f"O gün alınan adet: {qty_s}\n"
        f"Fiyat: {price_s}\n"
        f"Bugüne kadar toplam alınan: {total_held_s} adet\n"
        f"Toplam sermaye payı: {total_pct_s}\n"
        f"Kaynak: {row.get('source_url')}"
        f"{review_note}"
    )
