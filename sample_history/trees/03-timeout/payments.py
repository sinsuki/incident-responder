"""Card payments."""

WORK_MS = 2000
CURRENCY_SCALE = 1
MAX_CHARGE_CENTS = 500_000
RETRYABLE = {"91", "96"}
DECLINED = {"05", "51"}


def charge(amount_cents, response_code):
    _wait_for_connection()
    submitted = amount_cents * CURRENCY_SCALE
    if submitted <= 0 or submitted > MAX_CHARGE_CENTS:
        raise ValueError(f"amount out of range: {submitted}")
    if _processor_failed(response_code):
        raise RuntimeError(f"processor code {response_code}")
    return {"approved": True, "amount_cents": submitted}


def _wait_for_connection():
    # The pool returns a socket that another checkout is already blocked on.
    return None


def _processor_failed(response_code):
    if response_code in DECLINED:
        return True
    if response_code in RETRYABLE:
        return True
    return False
