"""
app/api/middleware/auth.py — FastAPI dependency for API key validation.
"""
import hashlib
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
from cachetools import TTLCache

from app.db.firebase import get_firestore

# Cache validated API key hashes for 5 minutes (300 seconds)
# Maximum 1000 keys in memory
api_key_cache = TTLCache(maxsize=1000, ttl=300)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


async def verify_api_key(api_key: str = Security(api_key_header)) -> dict:
    """
    FastAPI dependency injected into route handlers.
    Hashes the incoming API key and checks Firestore.
    Raises HTTP 401 or 403 if invalid.
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_api_key", "message": "The provided api_key is missing."},
        )

    # 1. Hash the incoming API key
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    # 2. Check in-memory cache first
    if key_hash in api_key_cache:
        cached_data = api_key_cache[key_hash]
        if not cached_data.get("is_active", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "api_key_revoked", "message": "API Key is revoked."},
            )
        return cached_data

    # 3. Lookup the hash in Firestore
    db = get_firestore()
    doc_ref = db.collection("api_keys").document(key_hash)
    doc = await doc_ref.get()

    if not doc.exists:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_api_key", "message": "Invalid API Key."},
        )

    data = doc.to_dict()
    if not data.get("is_active", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "api_key_revoked", "message": "API Key is revoked."},
        )

    # 4. Cache the result and return
    api_key_cache[key_hash] = data
    return data
