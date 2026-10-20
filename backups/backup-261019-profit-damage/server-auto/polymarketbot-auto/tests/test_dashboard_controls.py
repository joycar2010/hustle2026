from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from server import dashboard


def _request(token: str = "") -> Request:
    headers = [] if not token else [(b"x-operator-token", token.encode())]
    return Request({"type": "http", "method": "POST", "path": "/api/live/start", "headers": headers})


@pytest.mark.parametrize(
    "message",
    [
        "PolyApiException[status_code=400, error_message={'error': \"order couldn't be fully filled\"}]",
        "no orders found to match with FAK order",
    ],
)
def test_liquidity_rejection_is_retryable(message: str):
    assert dashboard._is_exit_unmatched_error(message)


def test_non_liquidity_exit_error_is_not_downgraded():
    assert not dashboard._is_exit_unmatched_error("not enough balance")
    assert not dashboard._is_exit_unmatched_error("invalid signature")


def test_live_control_requires_operator_token(monkeypatch):
    monkeypatch.setattr(dashboard, "_operator_token", lambda: "secret-token")
    with pytest.raises(HTTPException) as exc:
        dashboard._require_operator(_request("wrong-token"))
    assert exc.value.status_code == 401


def test_live_control_is_disabled_without_configured_token(monkeypatch):
    monkeypatch.setattr(dashboard, "_operator_token", lambda: "")
    with pytest.raises(HTTPException) as exc:
        dashboard._require_operator(_request("secret-token"))
    assert exc.value.status_code == 503
