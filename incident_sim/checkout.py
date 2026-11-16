"""One checkout: gateway calls orders, which calls inventory and payments.

Durations come from WORK_MS on the loaded revision. The service functions run,
but they do not sleep. The clock is simulated so a slow fault stays cheap.
"""

from __future__ import annotations

import random

from opentelemetry.trace import SpanKind, Status, StatusCode, set_span_in_context

from incident_sim.clock import MS
from incident_sim.telemetry import Session

AMOUNT_CENTS = 8000
SKU = "sku-1"
QTY = 1
GATEWAY_PRE_MS = 5
ORDERS_PRE_MS = 3
TAIL_MS = 2


def response_code(rng: random.Random) -> str:
    roll = rng.randrange(10)
    if roll < 8:
        return "00"
    if roll == 8:
        return "05"
    return "91"


def run_checkout(session: Session, revision, index: int, code: str, start_ns: int) -> int:
    order_id = f"ord-{index:04d}"
    inventory_ms = int(revision.inventory.WORK_MS)
    payments_ms = int(revision.payments.WORK_MS)
    timeout_ms = int(revision.orders.PAYMENTS_TIMEOUT_MS)
    timed_out = payments_ms > timeout_ms

    try:
        revision.inventory.reserve(SKU, QTY)
        reserve_error = None
    except ValueError as exc:
        reserve_error = str(exc)

    try:
        revision.payments.charge(AMOUNT_CENTS, code)
        charge_error = None
    except (ValueError, RuntimeError) as exc:
        charge_error = str(exc)

    gateway_start = start_ns
    orders_start = gateway_start + GATEWAY_PRE_MS * MS
    inventory_start = orders_start + ORDERS_PRE_MS * MS
    inventory_end = inventory_start + inventory_ms * MS
    payments_start = inventory_end
    server_end = payments_start + payments_ms * MS
    client_wait_ms = timeout_ms if timed_out else payments_ms
    client_end = payments_start + client_wait_ms * MS
    orders_end = client_end + TAIL_MS * MS
    gateway_end = orders_end + TAIL_MS * MS

    timeout_message = f"payments timed out after {timeout_ms}ms"
    if reserve_error:
        failure = reserve_error
        http_status = 502
    elif timed_out:
        failure = timeout_message
        http_status = 504
    elif charge_error:
        failure = charge_error
        http_status = 502
    else:
        failure = None
        http_status = 200

    if timed_out:
        client_error = timeout_message
    else:
        client_error = charge_error

    gateway = session.handles["gateway"]
    orders = session.handles["orders"]
    inventory = session.handles["inventory"]
    payments = session.handles["payments"]

    gateway_span = gateway.tracer.start_span(
        "POST /checkout",
        kind=SpanKind.SERVER,
        start_time=gateway_start,
        attributes={
            "http.request.method": "POST",
            "http.response.status_code": http_status,
            "http.route": "/checkout",
            "order.id": order_id,
        },
    )
    orders_span = orders.tracer.start_span(
        "create_order",
        context=_child(gateway_span),
        kind=SpanKind.INTERNAL,
        start_time=orders_start,
        attributes={"order.id": order_id},
    )
    inventory_span = inventory.tracer.start_span(
        "reserve",
        context=_child(orders_span),
        kind=SpanKind.SERVER,
        start_time=inventory_start,
        attributes={"order.id": order_id, "qty": QTY, "sku": SKU},
    )
    client_span = orders.tracer.start_span(
        "POST /charge",
        context=_child(orders_span),
        kind=SpanKind.CLIENT,
        start_time=payments_start,
        attributes={"order.id": order_id, "response.code": code},
    )
    # On a timeout the server span runs past the client that gave up.
    server_span = payments.tracer.start_span(
        "POST /charge",
        context=_child(client_span),
        kind=SpanKind.SERVER,
        start_time=payments_start,
        attributes={"amount.cents": AMOUNT_CENTS, "order.id": order_id, "response.code": code},
    )

    _finish(gateway_span, gateway_end, failure)
    _finish(orders_span, orders_end, failure)
    _finish(inventory_span, inventory_end, reserve_error)
    _finish(client_span, client_end, client_error)
    _finish(server_span, server_end, charge_error)

    session.record(gateway, gateway_end, (gateway_end - gateway_start) // MS, _status(failure))
    session.record(orders, orders_end, (orders_end - orders_start) // MS, _status(failure))
    session.record(inventory, inventory_end, inventory_ms, _status(reserve_error))
    session.record(payments, server_end, payments_ms, _status(charge_error))

    order_attrs = {"order.id": order_id}
    session.log(gateway, gateway_span, gateway_start, "INFO", "checkout accepted", order_attrs)
    session.log(orders, orders_span, orders_start, "INFO", "creating order", order_attrs)
    if reserve_error:
        session.log(inventory, inventory_span, inventory_end, "ERROR", f"reserve failed: {reserve_error}", order_attrs)
    else:
        session.log(inventory, inventory_span, inventory_end, "INFO", f"reserved {SKU} qty {QTY}", order_attrs)
    if timed_out:
        session.log(orders, client_span, client_end, "ERROR", timeout_message, order_attrs)
    if charge_error:
        session.log(payments, server_span, server_end, "ERROR", f"charge failed: {charge_error}", order_attrs)
    else:
        session.log(payments, server_span, server_end, "INFO", "charge approved", order_attrs)
    if failure:
        session.log(gateway, gateway_span, gateway_end, "ERROR", "checkout failed", order_attrs)
    else:
        session.log(gateway, gateway_span, gateway_end, "INFO", "checkout completed", order_attrs)

    return gateway_end


def _child(span):
    return set_span_in_context(span)


def _finish(span, end_ns: int, error: str | None) -> None:
    if error:
        span.set_status(Status(StatusCode.ERROR, error))
    else:
        span.set_status(Status(StatusCode.OK))
    span.end(end_time=end_ns)


def _status(error: str | None) -> str:
    if error:
        return "error"
    return "ok"
