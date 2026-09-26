"""
Entry point: fetch new BIST company-buyback disclosures from KAP, store them,
notify Telegram for anything new, and write the site's data file.

Usage:
    python -m tracker.main --days-back 7            # normal daily run
    python -m tracker.main --days-back 400 --silent  # first-time backfill, no Telegram spam
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

from .kap_buyback import KapClient, fetch_new_buybacks, load_store, save_store, merge_new_rows
from . import telegram_notify

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days-back", type=int, default=7,
                     help="how many days back to scan (KAP caps a single query window at ~2000 rows / ~7 days is safe)")
    ap.add_argument("--silent", action="store_true",
                     help="store data but skip Telegram messages (use for first backfill)")
    args = ap.parse_args()

    since = date.today() - timedelta(days=args.days_back)
    client = KapClient()

    log.info("Fetching KAP buyback disclosures from %s to today...", since)
    new_rows = fetch_new_buybacks(client, since=since)
    log.info("Found %d buyback disclosures in window.", len(new_rows))

    existing = load_store()
    merged, actually_new = merge_new_rows(existing, new_rows)
    save_store(merged)
    log.info("%d genuinely new disclosures (not seen before).", len(actually_new))

    if actually_new and not args.silent:
        for row in actually_new:
            telegram_notify.send(telegram_notify.format_buyback_message(row))

    needs_review = [r for r in actually_new if r.get("needs_review")]
    if needs_review:
        log.warning("%d new rows need manual review (parser couldn't extract all fields).", len(needs_review))


if __name__ == "__main__":
    main()
