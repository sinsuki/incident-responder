# Multi-Agent Incident Responder

Milestone 1 is a simulated checkout path: gateway, orders, inventory, and payments. It writes OpenTelemetry traces, logs, and metrics to local files and records which fault was injected. Later milestones add agents that read those files. This milestone does not call a model.

## Run

```bash
pip install -e '.[dev]'
python -m incident_sim --fault latency_spike --seed 1 --out runs/latency
pytest
```

Git is required, because the scenario loads service code from `sample_history/shop.bundle`. Docker is not.

`--requests` checkouts are served one after another. The first `--warmup` of them run the parent commit. The rest run the fault commit. `--seed` fixes trace ids and which processor response codes show up. Time is simulated, starting at 2026-01-15 15:00:00 UTC, so a slow fault does not make the process wait.

## Output

`runs/latency/` contains four files.

`traces.jsonl` is one span per line. A checkout is five spans: `POST /checkout` (gateway), `create_order` (orders), `reserve` (inventory), and `POST /charge` as a client span on orders plus a server span on payments. When payments runs past the orders deadline, the client span ends in error at that deadline and the payments span keeps going until `WORK_MS`.

`logs.jsonl` is one log per line. Each line has `timestamp_unix_nano`, `trace_id`, and `span_id`. The timestamp falls inside that span.

`metrics.jsonl` is one point per line, scraped once at the end of the warmup and once at the end of the run. Counters are named `requests`. Histograms are named `duration_ms`.

`ground_truth.json` names the fault, the service and file, the deployed commit, its parent, and `started_at_unix_nano` (the start of the first checkout served by the fault commit).

Span durations come from `WORK_MS` in the loaded service file. The functions do run; they just do not sleep.

## Faults

`python -m incident_sim --list-faults` prints this list.

| Fault | Service | What changes |
| --- | --- | --- |
| `latency_spike` | inventory | `reserve` rebuilds the catalog index and `WORK_MS` becomes 750. |
| `error_rate_spike` | payments | The retry check is inverted, so approval code `00` fails and retryable code `91` does not. |
| `dependency_timeout` | payments | Charge blocks for 2000ms. Orders gives up at `PAYMENTS_TIMEOUT_MS` (800). |
| `bad_deploy` | payments | `CURRENCY_SCALE` becomes 100, so an 8000 cent charge is rejected as 800000. |

Healthy payments still declines codes `05` and `91`, so a few warmup checkouts fail. The error-rate fault is the later jump, when code `00` starts failing.

## Sample history

`sample_history/trees/` holds a full snapshot of the four modules for the baseline and for each fault. `sample_history/build_repo.py` commits the baseline on `main` and each fault on its own branch, with fixed author dates, then writes `shop.bundle` and `commits.json`. A scenario checks out the parent and the fault commit and calls that code. The ground-truth commit is the one `git blame` attributes the fault line to.

Rebuild after editing a snapshot:

```bash
python sample_history/build_repo.py
```
