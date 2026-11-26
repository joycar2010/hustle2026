# Redemption monitor design

This component is intentionally a read-only monitor.  It polls the Polymarket
Data API v2 and records `redeemable`/`mergeable` positions in a local SQLite
idempotency ledger.  It never signs a transaction in its current form.

Direct `ConditionalTokens.redeemPositions` calls are unsafe for the current
deployment until the account model is verified: the Polymarket proxy wallet
that owns positions differs from the configured EOA signer.  A future P3
adapter must be an approved relayer with:

* explicit proxy-wallet authorization and an allowlist of CTF contract calls;
* one binary condition per request, parent collection id zero, and index sets
  `[1, 2]` only;
* idempotency by `(proxy_wallet, condition_id, token_id)` and recorded tx hash;
* chain-id/RPC/contract-code checks, balance and resolution checks;
* rate limits, a kill switch, and no transfer/withdrawal/address-management
  methods.

Run a safe poll:

```text
python redeem_worker.py --user 0x... --ledger /var/lib/poly-redeem/candidates.db
```

`--execute` is a guard-only mode and deliberately fails because no relayer
adapter is installed.  This prevents accidental direct wallet signing.
