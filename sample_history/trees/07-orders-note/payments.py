"""Card payments."""

WORK_MS = 40
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
