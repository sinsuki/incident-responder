"""Checkout entrypoint."""


def checkout(order_id, sku, qty):
    return {"order_id": order_id, "sku": sku, "qty": qty}
