"""
Low-level HTTP client for KAP (Kamuyu Aydınlatma Platformu) public JSON API.

No authentication is required; the endpoints are the same ones the
bildirim-sorgu web page itself calls. KAP runs a WAF that is sensitive to
request patterns, so this client:
  - does a one-time "warmup" GET to set session cookies before any POST
  - sends a Referer header matching the page a browser would be on
  - rate-limits itself (default: 2 req/s)
  - retries transient failures with backoff

Everything here is read-only / GET-and-POST-for-search, nothing writes to KAP.
"""
from __future__ import annotations

import os
import time
import logging
from typing import Any

import requests

log = logging.getLogger("kap_client")

BASE_URL = "https://www.kap.org.tr"
USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "kap-buyback-tracker/1.0 (kisisel takip botu; iletisim: gursah.pektas@ozu.edu.tr)",
)
MIN_INTERVAL = 0.5  # seconds between requests (~2 req/s)


class KapClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "tr",
            }
        )
        self._last_request_ts = 0.0
        self._warmed_up = False

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request_ts
        if elapsed < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - elapsed)

    def _warmup(self) -> None:
        if self._warmed_up:
            return
        try:
            self.session.get(f"{BASE_URL}/tr/bildirim-sorgu", timeout=15)
        except requests.RequestException as exc:
            log.warning("KAP warmup request failed (continuing anyway): %s", exc)
        self._warmed_up = True

    def _request(
        self,
        method: str,
        path: str,
        *,
        referer: str,
        json_body: dict | None = None,
        retries: int = 3,
    ) -> Any:
        self._warmup()
        url = f"{BASE_URL}{path}"
        last_exc: Exception | None = None
        for attempt in range(1, retries + 1):
            self._throttle()
            self._last_request_ts = time.time()
            try:
                resp = self.session.request(
                    method,
                    url,
                    json=json_body,
                    headers={"Referer": referer},
                    timeout=20,
                )
                if resp.status_code == 200:
                    return resp.json()
                log.warning(
                    "KAP %s %s -> HTTP %s (attempt %d/%d)",
                    method, path, resp.status_code, attempt, retries,
                )
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                log.warning("KAP %s %s failed (attempt %d/%d): %s", method, path, attempt, retries, exc)
            time.sleep(1.5 * attempt)
        raise RuntimeError(f"KAP request failed after {retries} attempts: {method} {path}") from last_exc

    def disclosures_by_criteria(
        self, from_date: str, to_date: str,
        mkk_member_oid_list: list[str] | None = None,
        subject_list: list[str] | None = None,
    ) -> list[dict]:
        """fromDate/toDate as 'YYYY-MM-DD'. Response capped at 2000 rows by KAP."""
        body = {
            "fromDate": from_date,
            "toDate": to_date,
            "mkkMemberOidList": mkk_member_oid_list or [],
            "subjectList": subject_list or [],
        }
        return self._request(
            "POST",
            "/tr/api/disclosure/members/byCriteria",
            referer=f"{BASE_URL}/tr/bildirim-sorgu",
            json_body=body,
        )

    def disclosure_detail(self, disclosure_index: int) -> dict:
        """Returns the detail payload (dict), unwrapping KAP's 1-element list response."""
        data = self._request(
            "GET",
            f"/tr/api/notification/attachment-detail/{disclosure_index}",
            referer=f"{BASE_URL}/tr/Bildirim/{disclosure_index}",
        )
        if isinstance(data, list):
            return data[0] if data else {}
        return data
