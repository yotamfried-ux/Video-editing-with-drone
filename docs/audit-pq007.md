# PQ-007 audit note

Selecting the right wave is not enough. Any PQ-007 fix must also prove that the final event window preserves setup, peak/action, and outcome.

Required metadata: original start/end, clamped start/end, final cut start/end, adjustment reason, peak/action time, outcome end, validation status, and validation reason.

Required tests: late-start events do not lose setup, early-end events do not lose outcome, dead-time-only windows are dropped, duration caps do not remove the action peak, and teaser windows are not taken from empty padding.
