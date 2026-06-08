import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.session import get_db
from app.api.auth import router as auth_router


@pytest.fixture
def auth_client():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    TestSession = sessionmaker(bind=eng)

    test_app = FastAPI()
    test_app.include_router(auth_router)

    def override_get_db():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    test_app.dependency_overrides[get_db] = override_get_db

    with TestClient(test_app) as client:
        yield client


class TestAuth:
    def test_init_creates_first_admin(self, auth_client):
        r = auth_client.post("/api/auth/init", json={
            "username": "admin", "password": "secret123"
        })
        assert r.status_code == 200
        assert r.json()["message"] == "Admin user created"

    def test_init_blocked_when_admin_exists(self, auth_client):
        auth_client.post("/api/auth/init", json={
            "username": "admin", "password": "secret123"
        })
        r = auth_client.post("/api/auth/init", json={
            "username": "admin2", "password": "pass"
        })
        assert r.status_code == 403

    def test_login_success(self, auth_client):
        auth_client.post("/api/auth/init", json={
            "username": "admin", "password": "secret123"
        })
        r = auth_client.post("/api/auth/login", json={
            "username": "admin", "password": "secret123"
        })
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password(self, auth_client):
        auth_client.post("/api/auth/init", json={
            "username": "admin", "password": "secret123"
        })
        r = auth_client.post("/api/auth/login", json={
            "username": "admin", "password": "wrong"
        })
        assert r.status_code == 401

    def test_login_nonexistent_user(self, auth_client):
        r = auth_client.post("/api/auth/login", json={
            "username": "nobody", "password": "pass"
        })
        assert r.status_code == 401
