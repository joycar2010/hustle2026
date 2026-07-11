from decimal import Decimal, ROUND_DOWN


def usdt_to_quantity(usdt_amount: Decimal, price: Decimal, step_size: str, min_qty: str) -> Decimal:
    step = Decimal(step_size)
    min_q = Decimal(min_qty)
    raw = usdt_amount / price
    rounded = (raw / step).to_integral_value(rounding=ROUND_DOWN) * step
    if rounded < min_q:
        return Decimal("0")
    return rounded


def round_to_step(quantity: Decimal, step_size: str) -> Decimal:
    step = Decimal(step_size)
    return (quantity / step).to_integral_value(rounding=ROUND_DOWN) * step
