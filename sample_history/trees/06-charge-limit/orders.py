"""Order creation.

PAYMENTS_TIMEOUT_MS is how long orders waits for payments.
"""

PAYMENTS_TIMEOUT_MS = 800


def create(order_id, sku, qty):
    return {"order_id": order_id, "sku": sku, "qty": qty}
