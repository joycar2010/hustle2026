import asyncio
from dataclasses import replace
from unittest.mock import Mock

import pytest

from server import dashboard


@pytest.mark.parametrize("address", ["", "   ", "invalid-address"])
@pytest.mark.parametrize("poller", ["poll_positions_loop", "poll_balance_loop"])
def test_unconfigured_wallet_never_queries_another_address(monkeypatch, address, poller):
    monkeypatch.setattr(
        dashboard,
        "cfg",
        replace(dashboard.cfg, funder_address=address, deposit_wallet_address=address),
    )
    state = {"positions": [{"size": 5}], "balance_pusd": 16.94, "value_usd": 1,
             "errors": {"positions": "old", "value": "old", "balance": "old"}}
    monkeypatch.setattr(dashboard, "_state", state)
    get = Mock(side_effect=AssertionError("Unexpected wallet HTTP request"))
    post = Mock(side_effect=AssertionError("Unexpected wallet RPC request"))
    monkeypatch.setattr(dashboard.requests, "get", get)
    monkeypatch.setattr(dashboard.requests, "post", post)

    async def stop_after_one_cycle(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(dashboard.asyncio, "sleep", stop_after_one_cycle)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(getattr(dashboard, poller)())
    get.assert_not_called()
    post.assert_not_called()
    if poller == "poll_positions_loop":
        assert state["positions"] == []
        assert state["value_usd"] is None
        assert "positions" not in state["errors"]
        assert "value" not in state["errors"]
    else:
        assert state["balance_pusd"] is None
        assert "balance" not in state["errors"]
