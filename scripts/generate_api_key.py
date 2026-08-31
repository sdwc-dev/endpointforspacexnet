import os
import sys
import secrets
import hashlib
import asyncio
from datetime import datetime, timezone

# Add the parent directory to sys.path to allow importing from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.firebase import init_firebase, get_firestore

async def create_api_key(client_name: str):
    print(f"Generating new API key for client: {client_name}")
    
    # 1. Generate a secure random 32-byte API key
    raw_api_key = "sk_live_" + secrets.token_urlsafe(32)
    
    # 2. Hash the key using SHA-256
    key_hash = hashlib.sha256(raw_api_key.encode()).hexdigest()
    
    # 3. Store the hash in Firestore
    print("Initializing Firebase...")
    init_firebase()
    db = get_firestore()
    
    doc_ref = db.collection("api_keys").document(key_hash)
    await doc_ref.set({
        "client_name": client_name,
        "is_active": True,
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    
    # 4. Give the plain text key to the admin (NEVER stored)
    print("\n" + "="*50)
    print(f"SUCCESS! Key generated for {client_name}")
    print("="*50)
    print(f"API Key: {raw_api_key}")
    print("\nIMPORTANT: Give this key to the client immediately.")
    print("It will NOT be shown again. We only stored the SHA-256 hash.")
    print(f"Hash stored: {key_hash}")
    print("="*50 + "\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/generate_api_key.py <client_name>")
        sys.exit(1)
        
    client_name = sys.argv[1]
    asyncio.run(create_api_key(client_name))
