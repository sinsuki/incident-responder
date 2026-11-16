"""Inventory reservation."""

WORK_MS = 750

CATALOG = {"sku-1": 100, "sku-2": 40}


def reserve(sku, qty):
    _rebuild_catalog_index()
    available = CATALOG.get(sku, 0)
    if qty <= 0 or qty > available:
        raise ValueError(f"cannot reserve {qty} of {sku}")
    return {"sku": sku, "qty": qty}


def _rebuild_catalog_index():
    # Moved here from the nightly job. Every reserve walks the catalog.
    index = {}
    for sku, count in CATALOG.items():
        index[sku] = count
    return index
