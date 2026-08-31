"""
app/db/firebase.py — Firebase Admin SDK initialization and Firestore client.
"""
import os
import firebase_admin
from firebase_admin import credentials, firestore_async
from app.config import settings

_app: firebase_admin.App | None = None


def init_firebase() -> None:
    """Initialize Firebase Admin SDK (idempotent — safe to call multiple times)."""
    global _app
    if _app is not None:
        return

    cred_path = settings.google_application_credentials
    project_id = settings.firebase_project_id

    if cred_path and os.path.exists(cred_path):
        # Local dev: service account JSON file
        cred = credentials.Certificate(cred_path)
        _app = firebase_admin.initialize_app(cred, {"projectId": project_id})
    else:
        # Cloud Run: use Application Default Credentials (Workload Identity)
        _app = firebase_admin.initialize_app(options={"projectId": project_id})


def get_firestore():
    """Return the async Firestore client. Call init_firebase() first."""
    return firestore_async.client()
