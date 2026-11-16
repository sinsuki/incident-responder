---
id: rollback-timeout
title: Roll back a slow dependency
kind: timeout
line: duration
---

# Roll back a slow dependency

The dependency runs longer than the caller waits. The implicated line is the dependency's own work time, not the caller deadline. Put the parent copy of that file back first. Then raise the caller timeout to the duration this incident measured, so the old deadline is not still below that work time.

## Roll back the slow dependency

action: rollback

Deploy `{file}` from parent `{parent}` in place of `{commit}`. The line `{line_text}` moved `{service}` from `{baseline_ms}`ms to `{incident_ms}`ms. The parent line is `{parent_text}`. The onset log is at `{timestamp}`.

## Raise the caller timeout

action: raise_timeout
file: orders.py
constant: PAYMENTS_TIMEOUT_MS

Set `{caller_constant}` in `{caller_file}` to `{timeout_value}`. The dependency took `{incident_ms}`ms. The deadline log is at `{timeout_timestamp}` and names `{timeout_ms}`ms.
