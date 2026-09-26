"""
Parser tests using an HTML fixture built to match KAP's real "Payların Geri
Alınmasına İlişkin Bildirim" layout, confirmed against a live TÜRK TELEKOM
(TTKOM) filing viewed on kap.org.tr on 2026-09-26 (three parts: an info
table, a multi-row transaction-detail table, and a narrative paragraph with
the all-time cumulative total).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tracker.kap_buyback import parse_buyback_detail, _parse_tl_number, _parse_date


# Mirrors the real TTKOM disclosure structure (values from the confirmed
# screenshot): info table + 2-row transaction detail table + narrative.
SAMPLE_HTML = """
<table>
  <tbody>
    <tr><td>Geri Alım İşlemini Gerçekleştiren Ortaklık</td><td>TÜRK TELEKOMÜNİKASYON A.Ş.</td></tr>
    <tr><td>Geri Alım İşlemine Konu Ortaklık</td><td>TÜRK TELEKOMÜNİKASYON A.Ş.</td></tr>
    <tr><td>Geri Alım İşleminin Niteliği</td><td>Geri Alım Programı Çerçevesinde</td></tr>
    <tr><td>Yönetim Kurulu Karar Tarihi</td><td>11.09.2026</td></tr>
    <tr><td>Varsa Geri Alım Programının Uygulanacağı Süre</td><td>Azami 3 yıl</td></tr>
    <tr><td>Geri Alıma Konu Azami Pay Miktarı (Nominal TL)</td><td>20.000.000</td></tr>
    <tr><td>Geri Alım İçin Ayrılan Fonun Toplam Tutarı (TL)</td><td>2.500.000.000</td></tr>
  </tbody>
</table>
<table>
  <tbody>
    <tr>
      <th>İşleme Konu Pay</th>
      <th>İşlem Tarihi</th>
      <th>İşleme Konu Payların Nominal Tutarı (TL)</th>
      <th>Sermayeye Oranı (%)</th>
      <th>İşlem Fiyatı (TL/Adet)</th>
      <th>Program Çerçevesinde Daha Önce Geri Alınan Payların Nominal Tutarı (TL)</th>
      <th>Varsa Bu Paylara Bağlı İmtiyazlar</th>
    </tr>
    <tr>
      <td>D Grubu, TTKOM, TRETTLK00013</td>
      <td>23.09.2026</td>
      <td>375.000</td>
      <td>0,01071</td>
      <td>54,025</td>
      <td>0</td>
      <td></td>
    </tr>
    <tr>
      <td>D Grubu, TTKOM, TRETTLK00013</td>
      <td>25.09.2026</td>
      <td>365.000</td>
      <td>0,01043</td>
      <td>54,609</td>
      <td>375.000</td>
      <td></td>
    </tr>
  </tbody>
</table>
<p>
11 Eylül 2026 tarihli Yönetim Kurulu kararıyla başlatılan pay geri alım programı
kapsamında 25 Eylül 2026 tarihinde 365.000 adet pay geri alınmış ve Şirketimizin
sahip olduğu TTKOM payları 1.240.000 adede ulaşmıştır (Şirket sermayesinin oranı
%0,0354).
</p>
"""


def test_parse_tl_number():
    assert _parse_tl_number("375.000") == 375000.0
    assert _parse_tl_number("54,609") == 54.609
    assert _parse_tl_number("%0,0354") == 0.0354


def test_parse_date():
    assert _parse_date("25.09.2026") == "2026-09-25"
    assert _parse_date("no date here") is None


def test_parse_real_ttkom_style_disclosure():
    detail = {
        "disclosure": {"disclosureBasic": {"disclosureId": "ttkom-abc123"}},
        "disclosureBody": [SAMPLE_HTML],
    }
    row = parse_buyback_detail(
        disclosure_index=1700000,
        publish_date="26.09.2026 09:00:00",
        company_title="TÜRK TELEKOMÜNİKASYON A.Ş.",
        tickers="TTKOM",
        detail=detail,
    )
    # Latest (25.09.2026) transaction, not the earlier 23.09.2026 row:
    assert row.transaction_date == "2026-09-25"
    assert row.quantity == 365000.0
    assert row.price == 54.609
    assert row.pct_this_transaction == 0.01043
    # All-time cumulative total from the narrative, not the in-table
    # "previously bought within this filing" column:
    assert row.total_held_after == 1240000.0
    assert row.ownership_pct_after == 0.0354
    assert row.needs_review is False
    assert row.raw_fields == {}  # only populated for needs_review rows


def test_parse_buyback_detail_missing_body_flags_review():
    detail = {"disclosure": {"disclosureBasic": {"disclosureId": "xyz"}}, "disclosureBody": []}
    row = parse_buyback_detail(
        disclosure_index=1, publish_date="24.09.2026 09:00:00",
        company_title="X", tickers="X", detail=detail,
    )
    assert row.needs_review is True


def test_parse_buyback_detail_unrecognizable_table_flags_review_with_raw_fields():
    detail = {
        "disclosure": {"disclosureBasic": {"disclosureId": "weird"}},
        "disclosureBody": ["<table><tr><td>Bilinmeyen Alan</td><td>Bir Değer</td></tr></table>"],
    }
    row = parse_buyback_detail(
        disclosure_index=2, publish_date="24.09.2026 09:00:00",
        company_title="Y", tickers="Y", detail=detail,
    )
    assert row.needs_review is True
    assert "bilinmeyen alan" in row.raw_fields


if __name__ == "__main__":
    test_parse_tl_number()
    test_parse_date()
    test_parse_real_ttkom_style_disclosure()
    test_parse_buyback_detail_missing_body_flags_review()
    test_parse_buyback_detail_unrecognizable_table_flags_review_with_raw_fields()
    print("All tests passed.")
