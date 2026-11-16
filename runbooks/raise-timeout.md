---
id: raise-timeout
title: Raise a caller timeout
kind: timeout
line: timeout_constant
---

# Raise a caller timeout

The implicated line is the caller deadline, and it is below the dependency duration in the forensics stats. Raise that constant. Do not use this when the implicated line is the dependency's own work time: the caller would wait longer and the dependency would still be slow.

## Raise the deadline

action: raise_timeout

Set `{constant}` in `{file}` to `{timeout_value}`. The cited line `{line_text}` is below the `{incident_ms}`ms dependency time. The onset log is at `{timestamp}`.
