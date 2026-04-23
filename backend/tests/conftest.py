"""pytest config — inject the mandatory env vars so `app.core.config.settings` can import.

These tests are pure (no DB, no network, no event loop). conftest keeps test-only env
isolated from production `.env`.
"""
import os

os.environ.setdefault("SECRET_KEY", "test-only-secret-do-not-use-in-prod-0123456789")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1vbmx5LWZlcm5ldC1rZXktMDEyMzQ1Njc4OWFiY2Q=")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1:5432/test")
