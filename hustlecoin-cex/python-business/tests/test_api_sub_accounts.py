class TestSubAccountCRUD:
    def test_create_sub_account(self, api_client):
        resp = api_client.post("/api/sub-accounts/", json={
            "note": "test001",
            "email": "test@example.com",
            "api_key": "key123",
            "api_secret": "secret_very_long_string",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["note"] == "test001"
        assert data["api_key"] == "key123"
        assert data["is_enabled"] is True

    def test_list_sub_accounts(self, api_client):
        api_client.post("/api/sub-accounts/", json={
            "note": "acct1", "email": "a@b.com",
            "api_key": "k1", "api_secret": "s1",
        })
        api_client.post("/api/sub-accounts/", json={
            "note": "acct2", "email": "b@b.com",
            "api_key": "k2", "api_secret": "s2",
        })
        resp = api_client.get("/api/sub-accounts/")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_update_sub_account(self, api_client):
        create = api_client.post("/api/sub-accounts/", json={
            "note": "before", "email": "a@b.com",
            "api_key": "k1", "api_secret": "s1",
        })
        acct_id = create.json()["id"]
        resp = api_client.put(f"/api/sub-accounts/{acct_id}", json={
            "note": "after",
        })
        assert resp.status_code == 200
        assert resp.json()["note"] == "after"

    def test_delete_soft(self, api_client):
        create = api_client.post("/api/sub-accounts/", json={
            "note": "todel", "email": "a@b.com",
            "api_key": "k1", "api_secret": "s1",
        })
        acct_id = create.json()["id"]
        resp = api_client.delete(f"/api/sub-accounts/{acct_id}")
        assert resp.status_code == 200
        assert "disabled" in resp.json()["message"]

        detail = api_client.get(f"/api/sub-accounts/{acct_id}")
        assert detail.json()["is_enabled"] is False

    def test_secret_masked(self, api_client):
        api_client.post("/api/sub-accounts/", json={
            "note": "mask", "email": "a@b.com",
            "api_key": "k1", "api_secret": "abcdefgh12345678",
        })
        resp = api_client.get("/api/sub-accounts/")
        data = resp.json()[0]
        assert data["api_secret_masked"].startswith("****")
        assert data["api_secret_masked"].endswith("5678")
