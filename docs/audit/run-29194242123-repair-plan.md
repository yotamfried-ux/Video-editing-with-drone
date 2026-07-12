# Run 29194242123 repair plan

## Production findings

Workflow run `29194242123` completed technically but exposed four deterministic failures:

1. Values such as `2.00–2.52`, `5.46–6.19`, and `7.39–7.55` represented `MM.SS` ranges but were discarded as sub-second decimal fragments.
2. QA re-edit rewrote a longer clip to the same path while path-only FFprobe caching retained the old 11-second duration, causing an early fade to black.
3. Every PREMATURE_CUT retry promoted the previous retry window to the original selector window, breaking candidate-to-draft reconciliation.
4. Mixed-subject telemetry aggregated tracks visible at different times and ignored the explicit primary-actor gate.

## Repair contracts

### 1. Parser-entry timestamp recovery

Recovery occurs before `analyzer._parse_session` and selector fragment filtering. Decimal seconds remain authoritative whenever they yield a usable event. `MM.SS` is accepted only when decimal duration is unusable, both second fields are valid (`00–59`), and the interpreted action reaches the configured minimum duration.

The same recovered event set feeds:

```text
analyzer parser → chunk timeline → selector telemetry → editor
```

Raw and interpreted values remain available as evidence:

```text
timestamp_encoding
timestamp_recovered
raw_timestamp_window
interpreted_timestamp_window
```

### 2. Mutable media duration cache

FFprobe duration cache keys now include:

```text
path + inode + mtime_ns + ctime_ns + size
```

This preserves caching for an unchanged file while invalidating both in-place rewrites and atomic same-path replacements, including same-size replacements.

### 3. Immutable selector provenance

Every QA repair retains separate windows:

```text
selector_original_window
previous_iteration_window
requested_end
final_render_window
```

For the production sequence:

```text
496–512.5 → 496–515.5 → 496–521.5
```

`496–512.5` remains immutable selector provenance and `496–521.5` remains the final rendered window.

### 4. Primary-actor subject reporting

Mixed-subject evaluation now uses final-cut windows and frame-level concurrency. All actor gates are considered; any blocking actor gate wins. Background players or surfers are allowed when the explicit primary-actor decision allows them. Missing or invalid policy evidence produces `inconclusive`, never a guessed pass.

## Automated acceptance

- [x] Production MM.SS examples are recovered before fragment filtering.
- [x] Invalid compact seconds still follow normal rejection rules.
- [x] Selector and analyzer consume the same recovered physical windows.
- [x] Same-path and same-size clip replacements invalidate duration cache.
- [x] Selector provenance survives multiple QA iterations.
- [x] Allowed background people do not trigger a false hard block.
- [x] A conflicting blocking actor gate remains blocking.
- [x] Missing final-window or policy evidence remains inconclusive.

Merge still requires every repository workflow and review thread to pass on the final head. A new production run is required after merge before claiming footage-level improvement.