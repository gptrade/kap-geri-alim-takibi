"""
Tracks Borsa Istanbul companies buying back their own shares.

Source: KAP (kap.org.tr) disclosures with subject "Payların Geri Alınmasına
İlişkin Bildirim" (Share Buyback Notification) - filed by a company itself
(disclosureClass == "ODA") each time it executes a repurchase under its
board-approved buyback program.

For each disclosure we try to extract, from the structured HTML table in
`disclosureBody`:
  - transaction date(s)
  - price / price range paid
  - number of shares bought that day
  - total shares held under the buyback program after the transaction
  - resulting % of capital held

KAP's exact table markup is not guaranteed to stay stable and this project
could not be live-tested against KAP from the build sandbox (no network
egress there), so the parser is defensive: it never throws away a
disclosure it can't fully parse. Anything it can't confidently extract is
flagged `needs_review=True` and the raw HTML + PDF link are kept so a human
(or a re-run after fixing the parser) can still get the numbers.
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
# https://<user>.github.io/<repo>/kap-buybacks.json alongside the page itself -
# matching how the existing tracker keeps its own data.json next to index.html.
DATA_DIR = Path(os.environ.get("KAP_DATA_DIR", "site"))
STORE_PATH = DATA_DIR / "kap-buybacks.json"

# The exact subject string KAP uses for company self-buyback execution notices.
BUYBACK_SUBJECTS = [
    "Payların Geri Alınmasına İlişkin Bildirim",
]

TL_NUMBER_RE = re.compile(r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?")
DATE_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")


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
    transaction_date: str | None
    price: float | None
    price_low: float | None
    price_high: float | None
    quantity: float | None
    total_held_after: float | None
    ownership_pct_after: float | None
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
    """KAP's ODA taxonomy tables are laid out as <tr><td>Label</td><td>Value</td></tr>.
    Collect every such pair, keyed by normalized (lowercased, stripped) label text.
    Later rows win on duplicate labels (KAP sometimes repeats headers per sub-table)."""
    pairs: dict[str, str] = {}
    for tr in soup.find_all("tr"):
        tds = tr.find_all(["td", "th"])
        if len(tds) < 2:
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
        quantity=None, total_held_after=None, ownership_pct_after=None,
        source_url=source_url,
    )

    if not html:
        row.needs_review = True
        return row

    soup = BeautifulSoup(html, "html.parser")
    pairs = _label_value_pairs(soup)
    row.raw_fields = pairs

    tx_date_raw = _find_field(pairs, "işlem tarih")
    row.transaction_date = _parse_date(tx_date_raw) if tx_date_raw else None

    price_raw = (
        _find_field(pairs, "işlem fiyat")
        or _find_field(pairs, "fiyat aral")
        or _find_field(pairs, "birim fiyat")
    )
    if price_raw:
        # price may be a single value ("18,45") or a range ("18,45 - 18,48")
        nums = TL_NUMBER_RE.findall(price_raw)
        if len(nums) >= 2:
            row.price_low = _parse_tl_number(nums[0])
            row.price_high = _parse_tl_number(nums[1])
        elif len(nums) == 1:
            row.price = _parse_tl_number(nums[0])

    qty_raw = (
        _find_field(pairs, "işlem", "aded")
        or _find_field(pairs, "alınan pay", "aded")
        or _find_field(pairs, "pay adedi")
    )
    row.quantity = _parse_tl_number(qty_raw) if qty_raw else None

    held_raw = (
        _find_field(pairs, "toplam", "geri alınan")
        or _find_field(pairs, "işlem sonras", "pay")
        or _find_field(pairs, "sahip olunan")
    )
    row.total_held_after = _parse_tl_number(held_raw) if held_raw else None

    pct_raw = (
        _find_field(pairs, "sermayedeki pay")
        or _find_field(pairs, "sermaye", "%")
        or _find_field(pairs, "oran")
    )
    if pct_raw:
        pct = _parse_tl_number(pct_raw)
        row.ownership_pct_after = pct

    # Consider it a full parse only if we got the core numbers.
    if row.transaction_date is None or row.quantity is None:
        row.needs_review = True

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
