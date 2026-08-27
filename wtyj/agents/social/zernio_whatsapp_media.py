"""Authenticated, bounded WhatsApp media retrieval for Ali reservation V2.

Zernio webhook attachments provide a WhatsApp media id.  This module retrieves
the bytes immediately from Zernio's authenticated endpoint and never exposes or
persists a provider URL.  Content validation and private persistence remain the
responsibility of ``ali_customer_dossier``.
"""

from __future__ import annotations

import os
import re
import urllib.parse

import requests


ZERNIO_BASE_URL = "https://zernio.com/api/v1"
MAX_MEDIA_BYTES = 10 * 1024 * 1024
_PROVIDER_ID = re.compile(r"^[A-Za-z0-9._~:-]{1,240}$")


class ZernioMediaError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def download_whatsapp_media(
    media_id: str,
    account_id: str,
    *,
    max_bytes: int = MAX_MEDIA_BYTES,
) -> dict:
    """Return authenticated media bytes without following provider redirects."""
    media_id = str(media_id or "").strip()
    account_id = str(account_id or "").strip()
    api_key = str(os.environ.get("LATE_API_KEY") or "").strip()
    if (
        not api_key
        or not _PROVIDER_ID.fullmatch(media_id)
        or not _PROVIDER_ID.fullmatch(account_id)
        or isinstance(max_bytes, bool)
        or not 1 <= int(max_bytes) <= MAX_MEDIA_BYTES
    ):
        raise ZernioMediaError("invalid_media_request")

    url = (
        f"{ZERNIO_BASE_URL}/whatsapp/media/"
        f"{urllib.parse.quote(media_id, safe='')}"
    )
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            params={"accountId": account_id},
            timeout=20,
            allow_redirects=False,
            stream=True,
        )
    except requests.RequestException as exc:
        raise ZernioMediaError("media_transport_failed", retryable=True) from exc

    if 300 <= response.status_code < 400 or response.headers.get("Location"):
        raise ZernioMediaError("media_redirect_rejected")
    if response.status_code in {408, 409, 425, 429} or response.status_code >= 500:
        raise ZernioMediaError("media_provider_unavailable", retryable=True)
    if not 200 <= response.status_code < 300:
        raise ZernioMediaError("media_provider_rejected")

    try:
        declared = int(response.headers.get("Content-Length") or 0)
    except (TypeError, ValueError) as exc:
        raise ZernioMediaError("invalid_media_length") from exc
    if declared < 0 or declared > int(max_bytes):
        raise ZernioMediaError("media_too_large")

    chunks = []
    total = 0
    try:
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > int(max_bytes):
                raise ZernioMediaError("media_too_large")
            chunks.append(chunk)
    except requests.RequestException as exc:
        raise ZernioMediaError("media_stream_failed", retryable=True) from exc
    if not total:
        raise ZernioMediaError("empty_media")

    return {
        "payload": b"".join(chunks),
        "content_type": str(
            response.headers.get("Content-Type") or ""
        ).split(";", 1)[0].strip().lower(),
        "size_bytes": total,
    }
