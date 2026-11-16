"""One OpenTelemetry pipeline per service, all writing the same local files.

The metrics SDK stamps data points with time.time_ns and has no clock argument.
bind_metric_clock points those module-level functions at the simulated clock so
a run does not depend on the wall clock.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path

from opentelemetry._logs import SeverityNumber
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor
from opentelemetry.sdk.metrics import AlwaysOffExemplarFilter, MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.trace import set_span_in_context

from incident_sim.clock import START_NS, Clock
from incident_sim.exporters import JsonlLogExporter, JsonlSpanExporter, attributes, dumps, number
from incident_sim.ids import SeededIdGenerator

SERVICES = ("gateway", "orders", "inventory", "payments")

# These modules do `from time import time_ns`, so the name is local to each one.
_METRIC_CLOCK_MODULES = (
    "opentelemetry.sdk.metrics._internal.instrument",
    "opentelemetry.sdk.metrics._internal._view_instrument_match",
    "opentelemetry.sdk.metrics._internal.metric_reader_storage",
)

_BUCKETS = (10, 25, 50, 100, 250, 500, 1000, 2500)


@dataclass
class Handle:
    name: str
    tracer: object
    logger: object
    requests: object
    duration: object


def bind_metric_clock(clock: Clock) -> list[tuple[object, object]]:
    saved = []
    for name in _METRIC_CLOCK_MODULES:
        module = importlib.import_module(name)
        saved.append((module, module.time_ns))
        module.time_ns = clock.now_ns
    return saved


def restore_metric_clock(saved: list[tuple[object, object]]) -> None:
    for module, original in saved:
        module.time_ns = original


class Session:
    def __init__(self, out: Path, seed: int) -> None:
        self.out = out
        self.seed = seed
        self.clock = Clock()
        self.handles: dict[str, Handle] = {}
        self._saved_clock: list[tuple[object, object]] | None = None
        self._providers: list = []
        self._readers: list[InMemoryMetricReader] = []
        self._metrics_path = out / "metrics.jsonl"
        self._metrics_lines: list[str] = []

    def __enter__(self) -> "Session":
        self._saved_clock = bind_metric_clock(self.clock)
        self.clock.set(START_NS)
        ids = SeededIdGenerator(self.seed)
        span_exporter = JsonlSpanExporter(self.out / "traces.jsonl")
        log_exporter = JsonlLogExporter(self.out / "logs.jsonl")
        for name in SERVICES:
            resource = Resource({"service.name": name})
            tracer_provider = TracerProvider(
                resource=resource,
                sampler=ALWAYS_ON,
                id_generator=ids,
                shutdown_on_exit=False,
            )
            tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
            logger_provider = LoggerProvider(resource=resource, shutdown_on_exit=False)
            logger_provider.add_log_record_processor(SimpleLogRecordProcessor(log_exporter))
            reader = InMemoryMetricReader()
            meter_provider = MeterProvider(
                metric_readers=[reader],
                resource=resource,
                exemplar_filter=AlwaysOffExemplarFilter(),
                shutdown_on_exit=False,
            )
            meter = meter_provider.get_meter("incident_sim")
            self.handles[name] = Handle(
                name=name,
                tracer=tracer_provider.get_tracer("incident_sim"),
                logger=logger_provider.get_logger(name),
                requests=meter.create_counter("requests", unit="1", description="Checkout requests"),
                duration=meter.create_histogram(
                    "duration_ms",
                    unit="ms",
                    description="Handler duration",
                    explicit_bucket_boundaries_advisory=_BUCKETS,
                ),
            )
            self._providers.extend((tracer_provider, logger_provider, meter_provider))
            self._readers.append(reader)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            for provider in self._providers:
                provider.shutdown()
            self._metrics_path.write_text("".join(self._metrics_lines), encoding="utf-8")
        finally:
            if self._saved_clock is not None:
                restore_metric_clock(self._saved_clock)
                self._saved_clock = None

    def log(self, handle: Handle, span, timestamp_ns: int, severity: str, body: str, attrs: dict) -> None:
        severity_number = SeverityNumber.ERROR if severity == "ERROR" else SeverityNumber.INFO
        handle.logger.emit(
            timestamp=timestamp_ns,
            observed_timestamp=timestamp_ns,
            context=set_span_in_context(span),
            severity_number=severity_number,
            severity_text=severity,
            body=body,
            attributes=attrs,
        )

    def record(self, handle: Handle, end_ns: int, duration_ms: int, status: str) -> None:
        self.clock.set(end_ns)
        attrs = {"status": status}
        handle.requests.add(1, attrs)
        handle.duration.record(duration_ms, attrs)

    def collect(self, time_ns: int) -> None:
        self.clock.set(time_ns)
        for reader in self._readers:
            data = reader.get_metrics_data()
            if data is None:
                continue
            for resource_metrics in data.resource_metrics:
                service = resource_metrics.resource.attributes.get("service.name")
                for scope_metrics in resource_metrics.scope_metrics:
                    for metric in scope_metrics.metrics:
                        self._metrics_lines.extend(_metric_lines(service, metric))


def _metric_lines(service, metric) -> list[str]:
    data = metric.data
    kind = type(data).__name__.lower()
    temporality = getattr(data, "aggregation_temporality", None)
    temporality_name = temporality.name.lower() if temporality is not None else ""
    lines = []
    for point in data.data_points:
        row = {
            "attributes": attributes(point.attributes),
            "name": metric.name,
            "service": service,
            "start_time_unix_nano": point.start_time_unix_nano,
            "temporality": temporality_name,
            "time_unix_nano": point.time_unix_nano,
            "type": kind,
        }
        if hasattr(point, "value"):
            row["value"] = number(point.value)
        else:
            row["bucket_counts"] = [int(count) for count in point.bucket_counts]
            row["count"] = int(point.count)
            row["explicit_bounds"] = [number(bound) for bound in point.explicit_bounds]
            row["max"] = number(point.max)
            row["min"] = number(point.min)
            row["sum"] = number(point.sum)
        lines.append(dumps(row) + "\n")
    return lines
