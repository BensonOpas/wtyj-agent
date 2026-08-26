"""Short-lived signed download URLs for Ali quote customer assets."""

from __future__ import annotations

import hmac
import json
import os
import re
import time
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlencode

from fastapi.responses import FileResponse, Response

from agents.social.ali_quote_workflow import get_quote
from agents.social.ali_quote_presentation import build_quote_filename


def sign_download(public_id: str, expires: int, secret: str) -> str:
    if not secret:
        raise ValueError("Signed-download secret is not configured")
    payload = f"{public_id}:{int(expires)}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, sha256).hexdigest()


def build_signed_url(
    base_url: str,
    public_id: str,
    secret: str,
    now: int | None = None,
    *,
    asset: str = "pdf",
) -> str:
    if asset not in {"pdf", "image", "confirmation"}:
        raise ValueError("Unsupported quote asset")
    now = int(time.time()) if now is None else int(now)
    expires = now + 3600
    signed_id = (
        f"{public_id}--image"
        if asset == "image"
        else f"{public_id}--confirmation"
        if asset == "confirmation"
        else public_id
    )
    signature = sign_download(signed_id, expires, secret)
    return f"{base_url.rstrip('/')}/api/public/ali-quote/{signed_id}?{urlencode({'expires': expires, 'signature': signature})}"


def verify_download(public_id: str, expires: int, signature: str, secret: str, now: int | None = None) -> bool:
    now = int(time.time()) if now is None else int(now)
    if expires < now or expires > now + 3600:
        return False
    expected = sign_download(public_id, expires, secret)
    return hmac.compare_digest(expected, str(signature or ""))


def quote_download_response(public_id: str, expires: int, signature: str):
    secret = os.environ.get("ALI_QUOTE_DOWNLOAD_SECRET", "")
    if not verify_download(public_id, expires, signature, secret):
        return Response(status_code=404)
    confirmation_asset = public_id.endswith("--confirmation")
    if confirmation_asset:
        from agents.social.ali_reservation_workflow import get_reservation

        reservation_id = public_id[:-14]
        reservation = get_reservation(reservation_id)
        path = Path(str((reservation or {}).get("confirmation_pdf_path") or "")).resolve()
        root = Path(
            os.environ.get(
                "ALI_RESERVATION_DATA_ROOT", "/app/data/ali-reservations",
            )
        ).resolve()
        try:
            path.relative_to(root)
        except (ValueError, OSError):
            return Response(status_code=404)
        if (
            not path.is_file()
            or not (reservation or {}).get("confirmation_pdf_sha256")
            or (reservation or {}).get("status") != "confirmed"
        ):
            return Response(status_code=404)
        reference = re.sub(
            r"[^A-Za-z0-9_-]", "-",
            str((reservation or {}).get("confirmation_reference") or "confirmation"),
        )[:100]
        return FileResponse(
            str(path),
            media_type="application/pdf",
            filename=f"Ali-Car-Rental-Reservation-{reference}.pdf",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    image_asset = public_id.endswith("--image")
    quote_id = public_id[:-7] if image_asset else public_id
    quote = get_quote(quote_id)
    path_key = "brand_image_path" if image_asset else "pdf_path"
    digest_key = "brand_image_sha256" if image_asset else "pdf_sha256"
    path = Path(str((quote or {}).get(path_key) or "")).resolve()
    root = Path(os.environ.get("ALI_QUOTE_DATA_ROOT", "/app/data/ali-quotes")).resolve()
    try:
        path.relative_to(root)
    except (ValueError, OSError):
        return Response(status_code=404)
    if not path.is_file() or not (quote or {}).get(digest_key):
        return Response(status_code=404)
    if image_asset:
        return FileResponse(
            str(path), media_type="image/png",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    try:
        customer = json.loads(quote.get("customer_json") or "{}")
        pricing = json.loads(quote.get("pricing_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        customer, pricing = {}, {}
    filename = build_quote_filename(
        customer.get("name", ""), quote.get("quote_reference", ""),
        pricing.get("createdAt", ""),
    )
    return FileResponse(
        str(path), media_type="application/pdf", filename=filename,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
