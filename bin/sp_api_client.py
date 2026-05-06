"""SP-API client: LWA refresh-token auth, retries, throttling.

Self-contained: imports only `requests`. No project-local imports.
"""
from __future__ import annotations

import os
import time
from typing import Any, Optional

import requests


REGION_ENDPOINTS = {
    "NA": "https://sellingpartnerapi-na.amazon.com",
    "EU": "https://sellingpartnerapi-eu.amazon.com",
    "FE": "https://sellingpartnerapi-fe.amazon.com",
}

LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"


class SpApiError(Exception):
    pass


class SpApiClient:
    def __init__(
        self,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        region: str = "NA",
        min_request_interval: float = 0.0,
    ) -> None:
        if region not in REGION_ENDPOINTS:
            raise SpApiError(
                f"Unknown SP_API_REGION '{region}'. Use one of: {', '.join(REGION_ENDPOINTS)}"
            )
        self._refresh_token = refresh_token
        self._client_id = client_id
        self._client_secret = client_secret
        self.region = region
        self.endpoint = REGION_ENDPOINTS[region]
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._min_request_interval = min_request_interval
        self._last_request_at: float = 0.0

    @classmethod
    def from_env(cls, min_request_interval: float = 0.0) -> "SpApiClient":
        """Build a client from the standard env vars.

        Required: LWA_CLIENT_ID, LWA_CLIENT_SECRET, SP_API_REFRESH_TOKEN.
        Optional: SP_API_REGION (default NA).
        """
        required = ["LWA_CLIENT_ID", "LWA_CLIENT_SECRET", "SP_API_REFRESH_TOKEN"]
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise SpApiError(
                "Missing required env var(s): "
                + ", ".join(missing)
                + ". See SETUP.md for how to get and set these."
            )
        return cls(
            refresh_token=os.environ["SP_API_REFRESH_TOKEN"],
            client_id=os.environ["LWA_CLIENT_ID"],
            client_secret=os.environ["LWA_CLIENT_SECRET"],
            region=os.environ.get("SP_API_REGION", "NA"),
            min_request_interval=min_request_interval,
        )

    def _get_access_token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        resp = requests.post(
            LWA_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            timeout=30,
        )
        if not resp.ok:
            raise SpApiError(
                f"LWA token exchange failed: {resp.status_code} {resp.text[:500]}"
            )
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        return self._access_token

    def _throttle(self) -> None:
        if self._min_request_interval <= 0:
            return
        elapsed = time.time() - self._last_request_at
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)

    def request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
        max_retries: int = 6,
    ) -> Any:
        url = f"{self.endpoint}{path}"
        attempt = 0
        backoff = 1.0
        while True:
            attempt += 1
            self._throttle()
            headers = {
                "x-amz-access-token": self._get_access_token(),
                "Accept": "application/json",
            }
            if json_body is not None:
                headers["Content-Type"] = "application/json"

            try:
                resp = requests.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=60,
                )
            except requests.exceptions.RequestException as e:
                # DNS failures, TLS errors, connection resets, read timeouts.
                # Retry transient network errors with backoff; surface as SpApiError
                # if we run out of attempts.
                if attempt < max_retries:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    continue
                raise SpApiError(
                    f"{method} {path} network error after {attempt} attempts: "
                    f"{type(e).__name__}: {e}"
                ) from e
            self._last_request_at = time.time()

            if resp.status_code == 401 and attempt < max_retries:
                self._access_token = None
                continue
            if resp.status_code == 429 and attempt < max_retries:
                retry_after = _parse_retry_after(resp.headers.get("Retry-After"), backoff)
                time.sleep(retry_after)
                backoff = min(backoff * 2, 60)
                continue
            if resp.status_code >= 500 and attempt < max_retries:
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue

            if not resp.ok:
                raise SpApiError(
                    f"{method} {path} -> {resp.status_code}: {resp.text[:800]}"
                )
            if not resp.text:
                return {}
            try:
                return resp.json()
            except ValueError as e:
                raise SpApiError(
                    f"{method} {path} returned non-JSON body: {resp.text[:200]!r}"
                ) from e


def _parse_retry_after(header_value: Optional[str], fallback: float) -> float:
    if not header_value:
        return fallback
    try:
        return max(float(header_value), fallback)
    except ValueError:
        return fallback
