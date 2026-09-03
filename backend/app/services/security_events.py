"""Signed outbound delivery for security and policy events."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from app.core.config import settings


logger = logging.getLogger(__name__)


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("SECURITY_WEBHOOK_URL은 http(s) URL이어야 합니다.")
    if settings.ENVIRONMENT == "production" and parsed.scheme != "https":
        raise ValueError("운영 환경의 보안 웹훅은 HTTPS를 사용해야 합니다.")


def _deliver(url: str, secret: str, payload: dict[str, Any]) -> dict[str, Any]:
    _validate_url(url)
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "MeshBoard/1.0"}
    if secret:
        signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        headers["X-MeshBoard-Signature"] = f"sha256={signature}"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=settings.SECURITY_WEBHOOK_TIMEOUT_SECONDS) as response:
        return {"delivered": 200 <= response.status < 300, "status_code": response.status}


async def emit_security_event(
    event_type: str,
    *,
    severity: str,
    attributes: dict[str, Any],
) -> dict[str, Any]:
    url = settings.SECURITY_WEBHOOK_URL.strip()
    payload = {
        "schema_version": "1.0",
        "event_type": event_type,
        "severity": severity,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "source": "meshboard",
        "attributes": attributes,
    }
    if not url:
        return {"configured": False, "delivered": False, "status_code": None}
    try:
        result = await asyncio.to_thread(
            _deliver, url, settings.SECURITY_WEBHOOK_SECRET, payload
        )
        return {"configured": True, **result}
    except (OSError, ValueError, urllib.error.URLError) as exc:
        logger.warning("Security webhook delivery failed: %s", exc)
        return {
            "configured": True,
            "delivered": False,
            "status_code": None,
            "error": type(exc).__name__,
        }
