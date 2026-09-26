"""
Tracks Borsa Istanbul companies buying back their own shares.

Source: KAP (kap.org.tr) disclosures with subject "Payların Geri Alınmasına
İlişkin Bildirim" (Share Buyback Notification) - filed by a company itself
each time it executes (or reports) repurchase transactions under its
board-approved buyback program.

Real KAP disclosure layout (confirmed from a live TÜRK TELEKOM/TTKOM filing,
2026-09-26) is three parts inside `disclosureBody`:

  1. A label/value info table: "Geri Alım İşlemini Gerçekleştiren Ortaklık",
     "Yönetim Kurulu Karar Tarihi", "Geri Alıma Konu Azami Pay Miktarı", etc.
  2. A multi-column "Geri Alım İşlemlerinin Detayları" table, one row per
     transaction date, with columns: İşlem Tarihi | İşleme Konu Payların
     Nominal Tutarı (TL) | Sermayeye Oranı (%) | İşlem Fiyatı (TL/Adet) |
     Program Çerçevesinde Daha Önce Geri Alınan Payların Nominal Tutarı (TL)
     (this last column is cumulative *within this filing only*, not the
     company's all-time total, so it is not used as the running total).
  3. An "Ek Açıklamalar" free-text paragraph that states the company's
     all-time cumulative buyback total and resulting % of capital, e.g.:
     "... 365.000 adet pay geri alınmış ve Şirketimizin sahip olduğu TTKOM
     payları 1.240.000 adede ulaşmıştır (Şirket sermayesinin oranı %0,0354)."

We take the most recent row of the detail table as "the latest transaction"
(date/quantity/price/this-transaction's % of capital), and pull the
all-time cumulative total + ownership % from the narrative paragraph via
regex, since that is the only place KAP states the true running total.

This structure was only confirmed against one real filing. Numeric label
wording can vary slightly between companies/filings, so every extraction
step is defensive: if the detail table or narrative numbers can't be found,
the row is flagged `needs_review=True` and a trimmed set of raw label/value
pairs is kept (only for review rows, to keep the data file small) so a
human can spot-check and the parser can be tuned further.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from pathlib import Path

from bs4 import BeautifulSoup

from .kap_client import KapClient, BASE_URL

log = logging.getLogger("kap_buyback")

# Lives inside site/ (not data/) so GitHub Pages serves it directly at
# https://<user>.github.io/<repo>/kap-buybacks.json alongside the page itself.
DATA_DIR = Path(os.environ.get("KAP_DATA_DIR", "site"))
STORE_PATH = DATA_DIR / "kap-buybacks.json"

# The exact subject string KAP uses for company self-buyback execution notices.
BUYBACK_SUBJECTS = [
    "Payların Geri Alınmasına İlişkin Bildirim",
]

TL_NUMBER_RE = re.compile(r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?")
DATE_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")

# "... 1.240.000 adede ulaşmıştır (Şirket sermayesinin oranı %0,0354)"
# Allow a bit of wording variance: "ulaşmıştır"/"ulaşılmıştır"/"olmuştur",
# "sermayesinin oranı"/"sermaye oranı"/"sermayedeki payı".
TOTAL_HELD_RE = re.compile(
    r"([\d.]+)\s*aded[ei]\s*ulaş\w*", re.IGNORECASE
)
TOTAL_PCT_RE = re.compile(
    r"sermay\w*\s*(?:oran[ıi]|pay[ıi])\D{0,15}%\s*([\d,]+)", re.IGNORECASE
)


def _parse_tl_number(s: str) -> float | None:
    """Turkish-formatted number: '.' = thousands sep, ',' = decimal sep."""
    m = TL_NUMBER_RE.search(s or "")
    if not m:
        return None
    raw = m.group(0).replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_date(s: str) -> str | None:
    m = DATE_RE.search(s or "")
    if not m:
        return None
    d, mo, y = m.groups()
    try:
        return date(int(y), int(mo), int(d)).isoformat()
    except ValueError:
        return None


def _publish_dt(publish_date: str) -> datetime | None:
    for fmt in ("%d.%m.%Y %H:%M:%S", "%Y.%m.%d %H:%M:%S"):
        try:
            return datetime.strptime(publish_date, fmt)
        except (ValueError, TypeError):
            continue
    return None


@dataclass
class BuybackRow:
    disclosure_index: int
    disclosure_id: str | None
    publish_date: str | None
    company_title: str | None
    tickers: str | None
    # Most recent transaction found in this filing's detail table:
    transaction_date: str | None
    price: float | None
    price_low: float | None
    price_high: float | None
    quantity: float | None            # shares bought on transaction_date
    pct_this_transaction: float | None  # % of capital added by that one transaction
    # All-time cumulative totals, from the filing's narrative paragraph:
    total_held_after: float | None     # total shares held under the program to date
    ownership_pct_after: float | None  # total % of capital held to date
    source_url: str
    needs_review: bool = False
    raw_fields: dict = field(default_factory=dict)


def _tr_lower(s: str) -> str:
    """Python's str.lower() turns Turkish 'İ' into 'i' + a combining dot-above
    (per Unicode's special casing rules), which then fails plain substring
    matches against needles typed as ordinary ASCII 'i'. Normalize 'İ'/'I' to
    plain 'i' first so label matching below is reliable."""
    return s.replace("İ", "i").replace("I", "i").lower()


def _label_value_pairs(soup: BeautifulSoup) -> dict[str, str]:
    """Two-column <tr><td>Label</td><td>Value</td></tr> rows (the info table
    above the transaction-detail table). Keyed by normalized label text."""
    pairs: dict[str, str] = {}
    for tr in soup.find_all("tr"):
        tds = tr.find_all(["td", "th"])
        if len(tds) != 2:
            continue
        label = tds[0].get_text(" ", strip=True)
        value = tds[1].get_text(" ", strip=True)
        if not label:
            continue
        pairs[_tr_lower(label)] = value
    return pairs


def _find_field(pairs: dict[str, str], *needles: str) -> str | None:
    for label, value in pairs.items():
        if all(n in label for n in needles):
            return value
    return None


def _find_detail_rows(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Find the multi-column 'Geri Alım İşlemlerinin Detayları' table (one
    row per transaction date) and return each data row as a dict keyed by
    its (normalized) column header. Returns [] if no such table is found."""
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header_cells = rows[0].find_all(["th", "td"])
        if len(header_cells) < 4:
            continue
        headers = [_tr_lower(c.get_text(" ", strip=True)) for c in header_cells]
        header_text = " | ".join(headers)
        if "işlem tarih" not in header_text or "fiyat" not in header_text:
            continue
        out = []
        for tr in rows[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) != len(headers):
                continue
            values = [c.get_text(" ", strip=True) for c in cells]
            out.append(dict(zip(headers, values)))
        if out:
            return out
    return []


def _detail_field(row: dict[str, str], *needles: str, exclude: str | None = None) -> str | None:
    for header, value in row.items():
        if exclude and exclude in header:
            continue
        if all(n in header for n in needles):
            return value
    return None


def parse_buyback_detail(disclosure_index: int, publish_date: str,
                          company_title: str, tickers: str,
                          detail: dict) -> BuybackRow:
    body_list = detail.get("disclosureBody") or []
    html = body_list[0] if body_list else ""
    disclosure_id = (
        detail.get("disclosure", {})
        .get("disclosureBasic", {})
        .get("disclosureId")
    )
    source_url = f"{BASE_URL}/tr/Bildirim/{disclosure_index}"

    row = BuybackRow(
        disclosure_index=disclosure_index,
        disclosure_id=disclosure_id,
        publish_date=publish_date,
        company_title=company_title,
        tickers=tickers,
        transaction_date=None,
        price=None, price_low=None, price_high=None,
        quantity=None, pct_this_transaction=None,
        total_held_after=None, ownership_pct_after=None,
        source_url=source_url,
    )

    if not html:
        row.needs_review = True
        return row

    soup = BeautifulSoup(html, "html.parser")

    # --- 1. Latest transaction from the detail table ---
    detail_rows = _find_detail_rows(soup)
    latest = None
    if detail_rows:
        parsed = [(_parse_date(_detail_field(r, "işlem tarih")), r) for r in detail_rows]
        dated = [(d, r) for d, r in parsed if d]
        if dated:
            latest_date, latest = max(dated, key=lambda pair: pair[0])
        else:
            latest = detail_rows[-1]  # fall back to last row, undated

    if latest:
        tx_date_raw = _detail_field(latest, "işlem tarih")
        row.transaction_date = _parse_date(tx_date_raw) if tx_date_raw else None

        qty_raw = _detail_field(latest, "nominal tutar", exclude="önce")
        row.quantity = _parse_tl_number(qty_raw) if qty_raw else None

        pct_raw = _detail_field(latest, "sermaye", "oran")
        row.pct_this_transaction = _parse_tl_number(pct_raw) if pct_raw else None

        price_raw = _detail_field(latest, "fiyat")
        if price_raw:
            nums = TL_NUMBER_RE.findall(price_raw)
            if len(nums) >= 2:
                row.price_low = _parse_tl_number(nums[0])
                row.price_high = _parse_tl_number(nums[1])
            elif len(nums) == 1:
                row.price = _parse_tl_number(nums[0])

    # --- 2. All-time cumulative total + % from the narrative paragraph ---
    full_text = soup.get_text(" ", strip=True)
    m_total = TOTAL_HELD_RE.search(full_text)
    if m_total:
        row.total_held_after = _parse_tl_number(m_total.group(1))
    m_pct = TOTAL_PCT_RE.search(full_text)
    if m_pct:
        row.ownership_pct_after = _parse_tl_number("%" + m_pct.group(1))

    # A full parse needs at least the latest transaction's date+quantity.
    # The cumulative narrative numbers are a bonus - flag review if missing
    # too, but don't discard the per-transaction data we did get.
    if row.transaction_date is None or row.quantity is None:
        row.needs_review = True

    if row.needs_review:
        # Keep a trimmed set of raw label/value pairs for debugging, capped
        # so a handful of bad disclosures can't blow up the data file size.
        pairs = _label_value_pairs(soup)
        if latest:
            pairs["__latest_detail_row__"] = str(latest)
        row.raw_fields = dict(list(pairs.items())[:20])
        row.raw_fields = {k: (v[:200] if isinstance(v, str) else v) for k, v in row.raw_fields.items()}

    return row


def _daterange_chunks(start: date, end: date, days: int = 7):
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=days - 1), end)
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def fetch_new_buybacks(client: KapClient, since: date, until: date | None = None) -> list[BuybackRow]:
    """Fetch and parse all buyback-execution disclosures published in [since, until]."""
    until = until or date.today()
    found: list[dict] = []
    for chunk_start, chunk_end in _daterange_chunks(since, until):
        try:
            results = client.disclosures_by_criteria(
                chunk_start.isoformat(), chunk_end.isoformat()
            )
        except RuntimeError as exc:
            log.error("Failed to fetch %s..%s: %s", chunk_start, chunk_end, exc)
            continue
        for item in results:
            if item.get("subject") in BUYBACK_SUBJECTS:
                found.append(item)

    rows: list[BuybackRow] = []
    for item in found:
        idx = item.get("disclosureIndex")
        if idx is None:
            continue
        try:
            detail = client.disclosure_detail(idx)
        except RuntimeError as exc:
            log.error("Failed to fetch detail for disclosureIndex=%s: %s", idx, exc)
            continue
        row = parse_buyback_detail(
            disclosure_index=idx,
            publish_date=item.get("publishDate"),
            company_title=item.get("kapTitle"),
            tickers=item.get("relatedStocks") or item.get("stockCodes"),
            detail=detail,
        )
        rows.append(row)
    return rows


def load_store() -> list[dict]:
    if STORE_PATH.exists():
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    return []


def save_store(rows: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rows_sorted = sorted(
        rows,
        key=lambda r: _publish_dt(r.get("publish_date") or "") or datetime.min,
        reverse=True,
    )
    STORE_PATH.write_text(
        json.dumps(rows_sorted, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def merge_new_rows(existing: list[dict], new_rows: list[BuybackRow]) -> tuple[list[dict], list[dict]]:
    """Dedup by disclosure_id (falls back to disclosure_index). Returns (merged, actually_new)."""
    seen = {
        (r.get("disclosure_id") or r.get("disclosure_index")) for r in existing
    }
    actually_new = []
    for row in new_rows:
        key = row.disclosure_id or row.disclosure_index
        if key in seen:
            continue
        seen.add(key)
        actually_new.append(asdict(row))
    return existing + actually_new, actually_new
