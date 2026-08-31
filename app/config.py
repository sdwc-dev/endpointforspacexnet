"""
app/config.py — Application settings loaded from environment variables.
"""
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv(override=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── SalesQL ─────────────────────────────────────────────────────
    saleql_api_key: str

    # ── Perplexity ──────────────────────────────────────────────────
    perplexity_model: str = "sonar"
    perplexity_temperature: float = 0.1
    perplexity_max_tokens: int = 1500

    @property
    def perplexity_api_keys(self) -> List[str]:
        import os
        keys = []
        for k, v in os.environ.items():
            if k.upper().startswith("PERPLEXITY_API_KEY") and v.strip():
                keys.append(v.strip())
        return list(dict.fromkeys(keys))  # preserve insertion/unique order

    # ── Gemini (Legacy fallback) ────────────────────────────────────
    @property
    def gemini_api_keys(self) -> List[str]:
        import os
        keys = []
        for k, v in os.environ.items():
            if k.upper().startswith("GEMINI_API_KEY") and v.strip():
                keys.append(v.strip())
        return list(set(keys))

    # API Auth is now database-backed via Firestore

    # ── Firebase & GCP ──────────────────────────────────────────────
    firebase_project_id: str = ""
    google_application_credentials: str = ""
    gcp_location: str = "us-central1"
    cloud_tasks_queue_name: str = "lead-enrichment"
    api_base_url: str = "http://localhost:8000"
    internal_auth_token: str = "super_secret_internal_token_123"

    # ── App ─────────────────────────────────────────────────────────
    app_env: str = "development"
    log_level: str = "INFO"

    # ── Processing ──────────────────────────────────────────────────
    max_concurrent_leads: int = 5
    rate_limit_per_minute: int = 40


settings = Settings()
