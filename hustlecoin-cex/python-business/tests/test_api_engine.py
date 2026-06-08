from datetime import datetime, timezone
from decimal import Decimal

from engine.models import Position, EngineState


class TestDashboard:
    def test_dashboard_empty(self, api_client):
        resp = api_client.get("/api/engine/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["engine_status"] == "STOPPED"
        assert data["positions_summary"]["total_open"] == 0
        assert data["positions_summary"]["total_closed"] == 0


class TestPositions:
    def test_list_empty(self, api_client):
        resp = api_client.get("/api/engine/positions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_summary_zeros(self, api_client):
        resp = api_client.get("/api/engine/positions/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_open"] == 0
        assert data["total_closed"] == 0
        assert float(data["total_pnl"]) == 0

    def test_position_not_found(self, api_client):
        resp = api_client.get("/api/engine/positions/999")
        assert resp.status_code == 404


class TestTradeLogs:
    def test_list_empty(self, api_client):
        resp = api_client.get("/api/engine/trade-logs")
        assert resp.status_code == 200
        assert resp.json() == []
