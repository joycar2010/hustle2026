class TestGlobalRules:
    def test_get_defaults(self, api_client):
        resp = api_client.get("/api/global-rules/")
        assert resp.status_code == 200
        data = resp.json()
        assert float(data["open_spread"]) == 0.8
        assert float(data["close_spread"]) == 0.2
        assert float(data["order_amount"]) == 500

    def test_partial_update(self, api_client):
        api_client.get("/api/global-rules/")
        resp = api_client.put("/api/global-rules/", json={
            "open_spread": 1.5,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert float(data["open_spread"]) == 1.5
        assert float(data["close_spread"]) == 0.2

    def test_full_update(self, api_client):
        resp = api_client.put("/api/global-rules/", json={
            "open_spread": 1.0,
            "close_spread": 0.3,
            "order_amount": 1000,
            "borrow_delay_sec": 5,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert float(data["open_spread"]) == 1.0
        assert float(data["close_spread"]) == 0.3
        assert float(data["order_amount"]) == 1000
        assert data["borrow_delay_sec"] == 5


class TestFundRules:
    def test_get_defaults(self, api_client):
        resp = api_client.get("/api/fund-rules/")
        assert resp.status_code == 200
        data = resp.json()
        assert float(data["bnb_min_quantity"]) == 0.15
        assert float(data["risk_value_threshold"]) == 1.5

    def test_partial_update(self, api_client):
        api_client.get("/api/fund-rules/")
        resp = api_client.put("/api/fund-rules/", json={
            "risk_value_threshold": 2.0,
        })
        assert resp.status_code == 200
        assert float(resp.json()["risk_value_threshold"]) == 2.0
        assert float(resp.json()["bnb_min_quantity"]) == 0.15
