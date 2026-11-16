---
id: revert-config
title: Revert a config constant
kind: error_rate
line: constant
---

# Revert a config constant

The new error matches a changed config constant. Put the parent value back on that one line and leave the rest of the deployed file in place. Rolling the whole file back would drop any other edit that shipped in the same revision.

## Restore the previous constant

action: revert_config

Set `{constant}` in `{file}` back to `{value}`, the value at parent `{parent}`. `{commit}` changed it to `{line_text}`. Leave every other line in the file. The onset log is at `{timestamp}`.
