# Multi-Agent Incident Responder

Milestone 1 is a simulated checkout path: gateway, orders, inventory, and payments. It writes OpenTelemetry traces, logs, and metrics to local files and records which fault was injected. The simulator does not call a model.

Milestone 2 is the log forensics agent. Given one run directory, it names the service and the onset of an error-rate or latency spike, and every claim cites a real log line plus a trace or span id. Later milestones add a code archaeologist, a runbook agent, and a citation-checked RCA report. Those agents are not in this tree.

## Run

```bash
pip install -e '.[dev]'
python -m incident_sim --fault latency_spike --seed 1 --out runs/latency
pytest
```

Git is required, because the scenario loads service code from `sample_history/shop.bundle`. Docker is not.

`--requests` checkouts are served one after another. The first `--warmup` of them run the parent commit. The rest run the fault commit. `--seed` fixes trace ids and which processor response codes show up. Time is simulated, starting at 2026-01-15 15:00:00 UTC, so a slow fault does not make the process wait.

## Log forensics

```bash
python -m incident_sim --fault latency_spike --seed 1 --out runs/latency
python -m log_forensics runs/latency
python -m log_forensics.eval
```

`python -m log_forensics` reads `traces.jsonl` and `logs.jsonl`. It does not read `ground_truth.json`. Metrics are scraped twice per run, so they only place a change inside a wide window. Spans and logs are one record per request, which is what the onset time needs.

The agent compares the requests before a candidate onset with the requests after it. Latency is the service's own span time, with child spans removed: a slow `reserve` also stretches orders and gateway, and the own-time view is what points at inventory. An error spike is a log message that is absent in the baseline window and common afterward, and only when that service fails most of the later requests. Steady payment declines (processor codes `05` and `91`) are not an incident. The search looks for one change that lasts until the end of the run, so a short blip that recovers can be missed.

The report is JSON (`schema_version` 1). `incident`, `service`, `kind` (`latency`, `timeout`, or `error_rate`), and `started_at_unix_nano` are the fields a later agent can branch on. `stats` holds the before/after duration or error rate and, for a new failure mode, the log message. `claims` is the cited evidence. `summary` is prose derived from those fields. `tokens.input` and `tokens.output` are 0 unless a model rewrote the summary.

A citation names `traces.jsonl` or `logs.jsonl`, a 1-based line, `timestamp_unix_nano`, and a `trace_id` or `span_id`. `python -m log_forensics` checks every citation against the file and exits 1 if any claim does not resolve. A claim with no log citation does not resolve. A healthy directory, or one with too few requests to form both windows, reports `incident: false` and no claims.

Set `LOG_FORENSICS_LLM=off` (the default) to keep the deterministic summary. `LOG_FORENSICS_LLM=openai` sends the evidence digest, not the raw files, to an OpenAI-compatible chat endpoint. `OPENAI_API_KEY` is required. `OPENAI_BASE_URL` and `OPENAI_MODEL` override the endpoint and the model (`gpt-4o-mini` by default). Token counts come from the response usage field.

`python -m log_forensics.eval` runs all four faults with seeds 1 through 5 (24 requests, 8 of them warmup) and prints, per fault, how often the service matches and how far the onset is from `started_at_unix_nano`. A case scores 1 when the service matches and the onset is exact. The score falls to 0 at 1000ms of error. A wrong service scores 0. A case passes when the service matches, the onset is within 1000ms, and the citations resolve. The command exits 1 if any case fails. It does not call a model unless `LOG_FORENSICS_LLM` is set.

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
