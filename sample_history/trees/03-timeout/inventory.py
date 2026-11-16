"""Inventory reservation."""

WORK_MS = 12

CATALOG = {"sku-1": 100, "sku-2": 40}


def reserve(sku, qty):
    available = CATALOG.get(sku, 0)
    if qty <= 0 or qty > available:
        raise ValueError(f"cannot reserve {qty} of {sku}")
    return {"sku": sku, "qty": qty}
