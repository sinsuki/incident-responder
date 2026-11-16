# Root cause analysis

## Summary

Inventory latency is on trace be6521cc3e2434e37af027bc08d6af57 at log timestamp 1768489202134000000.

The implicated line is inventory.py:3 in commit a3edb78641f743638593a6e04e47227d9f2960fe.

Mitigation starts with the runbook section Roll back the slow commit.

## Impact

Span f0dfb4a5d8a064df ran from 1768489201212000000 to 1768489201224000000 (12ms), and span 5dfbd3d12c4a3698 ran from 1768489201384000000 to 1768489202134000000 (750ms).

The log at 1768489202134000000 on span 5dfbd3d12c4a3698 says 'reserved sku-1 qty 1'.

The log at 1768489201224000000 on span f0dfb4a5d8a064df says 'reserved sku-1 qty 1'.

## Timeline

The log on span f0dfb4a5d8a064df is at 1768489201224000000.

Trace be6521cc3e2434e37af027bc08d6af57 starts at 1768489201376000000 on span 677f6cbdcc22af58.

The log on span 5dfbd3d12c4a3698 is at 1768489202134000000.

## Root cause

Commit a3edb78641f743638593a6e04e47227d9f2960fe sets `WORK_MS = 750` at inventory.py:3.

Commit 4e173e43679bc21d673eb259d409188bf09ece6f sets `WORK_MS = 12` at inventory.py:3.

## Evidence

Trace be6521cc3e2434e37af027bc08d6af57 starts at 1768489201376000000 on span 677f6cbdcc22af58; span 5dfbd3d12c4a3698 runs from 1768489201384000000 to 1768489202134000000; the log at 1768489202134000000 on span 5dfbd3d12c4a3698 says 'reserved sku-1 qty 1'.

Span f0dfb4a5d8a064df runs from 1768489201212000000 to 1768489201224000000; the log at 1768489201224000000 on span f0dfb4a5d8a064df says 'reserved sku-1 qty 1'.

Commit a3edb78641f743638593a6e04e47227d9f2960fe at inventory.py:3 reads `WORK_MS = 750`.

Commit 4e173e43679bc21d673eb259d409188bf09ece6f at inventory.py:3 reads `WORK_MS = 12`.

## Mitigation

Runbook section Roll back the slow commit cites log timestamp 1768489202134000000, commit a3edb78641f743638593a6e04e47227d9f2960fe, and commit 4e173e43679bc21d673eb259d409188bf09ece6f.

## Tokens

| Agent | Input | Output |
| --- | ---: | ---: |
| forensics | 0 | 0 |
| archaeologist | 0 | 0 |
| runbook | 0 | 0 |
| orchestrator | 0 | 0 |
| total | 0 | 0 |
