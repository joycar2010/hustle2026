import re
path = "/data/hustle2026/backend/app/services/account_service.py"
with open(path, "r") as f:
    c = f.read()

# Find the "else: raise ValueError" block and insert OKX handler before it
anchor = '            else:\n                raise ValueError(f"Unknown platform_id: {platform_id}")'
assert anchor in c, "anchor not found"

okx_block = '''            elif platform_id == 5:  # OKX
                from app.services.okx_client import OKXClient
                _okx = OKXClient(
                    api_key=account.api_key or "",
                    api_secret=account.api_secret or "",
                    passphrase=account.passphrase or "",
                    proxy_url=proxy_url,
                )
                try:
                    _okx_bal_raw, _okx_pos_raw = await asyncio.gather(
                        _okx.get_account_balance(),
                        _okx.get_positions(),
                        return_exceptions=True,
                    )
                    if isinstance(_okx_bal_raw, Exception):
                        logger.error(f"OKX balance failed for {account_id_str}: {_okx_bal_raw}")
                        _okx_bal_raw = {}
                    if isinstance(_okx_pos_raw, Exception):
                        logger.error(f"OKX positions failed for {account_id_str}: {_okx_pos_raw}")
                        _okx_pos_raw = []

                    _details = _okx_bal_raw.get("details", [])
                    _total_eq = float(_okx_bal_raw.get("totalEq", 0))
                    _avail = 0.0
                    for d in _details:
                        _avail += float(d.get("availBal", 0))
                    _upnl = float(_okx_bal_raw.get("upl", 0))
                    _frozen = _total_eq - _avail if _total_eq > _avail else 0.0

                    balance = AccountBalance(
                        total_assets=_total_eq,
                        available_balance=_avail,
                        net_assets=_total_eq,
                        frozen_assets=_frozen,
                        margin_balance=_total_eq,
                        unrealized_pnl=_upnl,
                        total_positions=len(_okx_pos_raw),
                        daily_pnl=_upnl,
                        funding_fee=0.0,
                        commission_fee=0.0,
                    )
                    positions = []
                    for p in _okx_pos_raw:
                        _pos_amt = float(p.get("pos", 0))
                        positions.append(AccountPosition(
                            symbol=p.get("instId", ""),
                            side="buy" if p.get("posSide") == "long" else "sell",
                            size=abs(_pos_amt),
                            entry_price=float(p.get("avgPx", 0)),
                            mark_price=float(p.get("markPx", 0)),
                            unrealized_pnl=float(p.get("upl", 0)),
                            leverage=int(float(p.get("lever", 0))),
                        ))
                    daily_pnl = _upnl
                except Exception as _oe:
                    logger.error(f"OKX account data failed for {account_id_str}: {_oe}")
                    balance = AccountBalance(
                        total_assets=0, available_balance=0, net_assets=0,
                        frozen_assets=0, margin_balance=0, unrealized_pnl=0,
                        total_positions=0, daily_pnl=0, funding_fee=0, commission_fee=0,
                    )
                    positions = []
                    daily_pnl = 0.0
                finally:
                    await _okx.close()
'''

c = c.replace(anchor, okx_block + anchor, 1)

with open(path, "w") as f:
    f.write(c)
print("OKX handler added to account_service")
