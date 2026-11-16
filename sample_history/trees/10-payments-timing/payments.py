"""Card payments."""

# The processor answers a little slower on the new path. Still well under the orders deadline.
WORK_MS = 48
CURRENCY_SCALE = 1
MAX_CHARGE_CENTS = 750_000
RETRYABLE = {"91", "96"}
DECLINED = {"05", "51"}


def charge(amount_cents, response_code):
    submitted = amount_cents * CURRENCY_SCALE
    if submitted <= 0 or submitted > MAX_CHARGE_CENTS:
        raise ValueError(f"amount out of range: {submitted}")
    if _processor_failed(response_code):
        raise RuntimeError(f"processor code {response_code}")
    return {"approved": True, "amount_cents": submitted}


def _processor_failed(response_code):
    if response_code in DECLINED:
        return True
    if response_code in RETRYABLE:
        return True
    return False


def format_receipt(order_id, amount_cents):
    # Returned to the caller for the email receipt. Charge does not use it.
    dollars = amount_cents / 100
    return f"{order_id} ${dollars:.2f}"
