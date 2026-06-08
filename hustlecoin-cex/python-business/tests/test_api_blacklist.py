class TestBlacklist:
    def test_add_and_list(self, api_client):
        resp = api_client.post("/api/blacklist/", json={
            "symbol": "BTCUSDT", "reason": "testing",
        })
        assert resp.status_code == 201
        assert resp.json()["symbol"] == "BTCUSDT"

        listing = api_client.get("/api/blacklist/")
        assert len(listing.json()) == 1

    def test_remove(self, api_client):
        api_client.post("/api/blacklist/", json={"symbol": "ETHUSDT"})
        resp = api_client.delete("/api/blacklist/ETHUSDT")
        assert resp.status_code == 200

        listing = api_client.get("/api/blacklist/")
        assert len(listing.json()) == 0

    def test_duplicate_returns_409(self, api_client):
        api_client.post("/api/blacklist/", json={"symbol": "SOLUSDT"})
        resp = api_client.post("/api/blacklist/", json={"symbol": "SOLUSDT"})
        assert resp.status_code == 409

    def test_bulk_import(self, api_client):
        resp = api_client.post("/api/blacklist/bulk", json={
            "symbols": ["AAVEUSDT", "LINKUSDT", "DOTUSDT"],
            "reason": "bulk test",
        })
        assert resp.status_code == 201
        assert "3" in resp.json()["message"]

        listing = api_client.get("/api/blacklist/")
        assert len(listing.json()) == 3
