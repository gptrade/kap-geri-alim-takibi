"""
Parser tests using a synthetic KAP-style ODA table (label/value <tr> pairs),
since the build environment has no network access to kap.org.tr to pull a
real fixture. Real KAP markup should be dropped in here (as a saved
disclosureBody HTML string) and re-tested the first time the tracker runs
for real - see README-KAP-EKLEME.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tracker.kap_buyback import parse_buyback_detail, _parse_tl_number, _parse_date


SAMPLE_HTML = """
<table class="tbl_oda-geri-alim">
  <tbody>
    <tr><td>İşlem Tarihi</td><td>24.09.2026</td></tr>
    <tr><td>İşlem Fiyat Aralığı (TL)</td><td>18,45 - 18,48</td></tr>
    <tr><td>İşlem Adedi</td><td>150.000</td></tr>
    <tr><td>İşlem Sonrası Sahip Olunan Pay Adedi</td><td>2.350.000</td></tr>
    <tr><td>Sermayedeki Payı (%)</td><td>%1,25</td></tr>
  </tbody>
</table>
"""


def test_parse_tl_number():
    assert _parse_tl_number("150.000") == 150000.0
    assert _parse_tl_number("18,45") == 18.45
    assert _parse_tl_number("%1,25") == 1.25


def test_parse_date():
    assert _parse_date("24.09.2026") == "2026-09-24"
    assert _parse_date("no date here") is None


def test_parse_buyback_detail_full():
    detail = {
        "disclosure": {"disclosureBasic": {"disclosureId": "abc123"}},
        "disclosureBody": [SAMPLE_HTML],
    }
    row = parse_buyback_detail(
        disclosure_index=999999,
        publish_date="24.09.2026 18:05:00",
        company_title="ÖRNEK SANAYİ A.Ş.",
        tickers="ORNEK",
        detail=detail,
    )
    assert row.transaction_date == "2026-09-24"
    assert row.price_low == 18.45
    assert row.price_high == 18.48
    assert row.quantity == 150000.0
    assert row.total_held_after == 2350000.0
    assert row.ownership_pct_after == 1.25
    assert row.needs_review is False


def test_parse_buyback_detail_missing_body_flags_review():
    detail = {"disclosure": {"disclosureBasic": {"disclosureId": "xyz"}}, "disclosureBody": []}
    row = parse_buyback_detail(
        disclosure_index=1, publish_date="24.09.2026 09:00:00",
        company_title="X", tickers="X", detail=detail,
    )
    assert row.needs_review is True


if __name__ == "__main__":
    test_parse_tl_number()
    test_parse_date()
    test_parse_buyback_detail_full()
    test_parse_buyback_detail_missing_body_flags_review()
    print("All tests passed.")
