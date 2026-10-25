"""Single-submit BNB conversion of an already-proven margin residual."""

from decimal import Decimal, InvalidOperation


class ResidualConversionError(Exception):
    def __init__(self, detail: str, status_code: int = 409):
        super().__init__(detail)
        self.status_code = status_code


def _number(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ResidualConversionError("Binance returned an invalid residual amount") from None
    if not result.is_finite() or result < 0:
        raise ResidualConversionError("Binance returned an invalid residual amount")
    return result


def _margin_asset(snapshot: object, asset: str) -> dict:
    rows = snapshot.get("userAssets") if isinstance(snapshot, dict) else None
    if not isinstance(rows, list):
        raise ResidualConversionError("Binance margin balance could not be verified", 503)
    matches = [row for row in rows if isinstance(row, dict) and row.get("asset") == asset]
    if len(matches) != 1:
        raise ResidualConversionError("Binance margin asset could not be verified", 503)
    return matches[0]


def _confirmed_result(result: object, asset: str, quantity: Decimal) -> dict | None:
    rows = result.get("transferResult") if isinstance(result, dict) else None
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        return None
    row = rows[0]
    source = row.get("fromAsset") or row.get("asset")
    if source != asset or row.get("targetAsset", "BNB") != "BNB":
        return None
    try:
        if _number(row.get("amount")) != quantity or _number(row.get("transferedAmount")) <= 0:
            return None
    except ResidualConversionError:
        return None
    if not row.get("tranId") and not row.get("transId"):
        return None
    return row


async def convert_margin_residual_to_bnb(
    client, asset: str, quantity: Decimal, *, pre_submit_guard
) -> dict:
    """The caller owns the account lease and has validated position provenance."""
    quantity = _number(quantity)
    if quantity <= 0:
        raise ResidualConversionError("No margin residual remains")
    try:
        quote = await client.get_dust_assets(
            account_type="MARGIN", pre_submit_guard=pre_submit_guard,
        )
    except Exception as exc:
        raise ResidualConversionError(
            f"{asset} BNB conversion eligibility could not be verified; no conversion submitted", 503,
        ) from exc
    details = quote.get("details") if isinstance(quote, dict) else None
    matches = [row for row in (details if isinstance(details, list) else [])
               if isinstance(row, dict) and row.get("asset") == asset]
    if len(matches) != 1:
        raise ResidualConversionError(
            f"Binance does not currently offer {asset} to BNB in the margin wallet; no conversion submitted"
        )
    quoted = matches[0]
    if _number(quoted.get("amountFree")) != quantity or _number(quoted.get("toBNBOffExchange")) <= 0:
        raise ResidualConversionError(
            f"{asset} margin conversion quote does not match the proven balance; no conversion submitted"
        )

    # Dust consumes the complete free balance of an asset. Re-read the actual
    # source wallet immediately before the one permitted conversion request.
    current = _margin_asset(await client.get_margin_account(), asset)
    if (
        _number(current.get("free")) != quantity
        or _number(current.get("locked")) > 0
        or _number(current.get("borrowed")) > 0
        or _number(current.get("interest")) > 0
    ):
        raise ResidualConversionError(
            f"{asset} margin balance or debt changed; no conversion submitted"
        )

    failure_code = ""
    try:
        result = await client.dust_to_bnb(
            [asset], account_type="MARGIN", pre_submit_guard=pre_submit_guard,
        )
    except Exception as exc:
        # Exception text can contain a signed request URL. Surface only the
        # exchange error code, and never retry a potentially accepted request.
        code = getattr(exc, "api_code", None)
        if isinstance(code, int):
            failure_code = f" (Binance code {code})"
        result = None
    confirmed = _confirmed_result(result, asset, quantity)
    if confirmed is None:
        state = "margin balance requires reconciliation"
        try:
            after = _margin_asset(await client.get_margin_account(), asset)
            if _number(after.get("free")) == quantity and _number(after.get("locked")) == 0:
                state = f"{quantity} {asset} remains in margin"
        except Exception:
            pass
        raise ResidualConversionError(
            f"{asset} BNB conversion was not confirmed{failure_code}; {state}; no retry or wallet transfer submitted",
            502,
        )
    return {"dust": result, "conversion": confirmed}
