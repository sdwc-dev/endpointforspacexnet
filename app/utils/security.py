"""
app/utils/security.py — API key validation and HMAC signing utilities.
"""
import hmac
import hashlib
import json
from typing import Optional
from app.config import settings



def sign_payload(payload: dict, secret: str) -> str:
    """
    Generate HMAC-SHA256 signature for a callback payload.
    Attach as X-Signature header for tamper detection.
    """
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hmac.new(
        secret.encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
