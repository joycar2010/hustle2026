class TestSymbolRules:
    def test_list_empty(self, api_client):
        resp = api_client.get("/api/symbol-rules/")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_auto_creates(self, api_client):
        resp = api_client.get("/api/symbol-rules/BTCUSDT")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "BTCUSDT"
        assert data["open_spread"] is None
        assert data["effective_open_spread"] is not None

    def test_update_override(self, api_client):
        resp = api_client.put("/api/symbol-rules/ETHUSDT", json={
            "open_spread": 1.5,
            "order_amount": 1000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert float(data["open_spread"]) == 1.5
        assert float(data["order_amount"]) == 1000
        assert float(data["effective_open_spread"]) == 1.5

    def test_reset_to_global(self, api_client):
        api_client.put("/api/symbol-rules/SOLUSDT", json={"open_spread": 2.0})
        resp = api_client.post("/api/symbol-rules/SOLUSDT/reset")
        assert resp.status_code == 200
        data = resp.json()
        assert data["open_spread"] is None
        assert data["source"] == "global"

    def test_delete(self, api_client):
        api_client.get("/api/symbol-rules/ADAUSDT")
        resp = api_client.delete("/api/symbol-rules/ADAUSDT")
        assert resp.status_code == 200

        listing = api_client.get("/api/symbol-rules/")
        symbols = [r["symbol"] for r in listing.json()]
        assert "ADAUSDT" not in symbols
