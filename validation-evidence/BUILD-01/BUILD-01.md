# BUILD-01 — APK identity and provenance

**Result: PASS**

| Field | Value |
| --- | --- |
| Executed | 2026-09-19T10:18:34Z |
| Workflow run | [35437001884](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35437001884) |
| Job | 105881262927, attempt 1, conclusion success |
| Harness commit | `d3d4700` |

## Build record, retrieved from EAS

```
BUILD01_platform='ANDROID'
BUILD01_appVersion='1.0.0'
BUILD01_appBuildVersion='2'
BUILD01_runtimeVersion='f8235e502eea89a62fac37d668b38f1542c997f9'
BUILD01_gitCommitHash='356d5812097ba935401ecf3a145a2608cda68cb9'
BUILD01_gitCommitMessage='Fix EAS APK download working directory (#210)...'
BUILD01_completedAt='2026-09-18T16:56:36.020Z'
BUILD01_channel='preview'
```

## Verdict

```
BUILD01_EXPECTED_SHA=356d5812097ba935401ecf3a145a2608cda68cb9
BUILD01_ACTUAL_SHA=356d5812097ba935401ecf3a145a2608cda68cb9
BUILD01_MATCH=true
BUILD01_VERDICT=PROVEN: binary was built from the expected commit
```

## Binary identity

```
BUILD01_APK_SHA256=997c3b4c047dc886df33b4dadbd1c43b0ccb13225576d500da7ed940daa47789
BUILD01_APK_BYTES=84409443
```

The same SHA-256 was independently recorded by the UI run (35436648784), so the
binary is reproducibly retrievable by build id.

## Relationship to GAP-003

The existing qualification workflow **asserted** `tested_app_commit` from a
hardcoded env var and never checked it. This experiment performed the check that
was missing, and the assertion turns out to be **correct**: the APK really was
built from `356d581`, which is also current `main` HEAD and the commit running
in production on Vercel.

So GAP-003 is a *verification* gap, not a false claim. It mattered because
nothing in the harness would have detected it had the build been stale — and
`eas build:view` failing (below) shows the check is not free to add.

## Tooling note

`eas build:view <id> --json --non-interactive` exits 1 on the pinned CLI
(`eas-version: 18.9.1`) with only `Error: build:view command failed.` and no
diagnostic — see run [35436939789](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35436939789).
Provenance had to be obtained via `eas build:list --json` and selecting the
record by id. Anyone adding this check to the production gates needs the
fallback.

## Not established

APK **signing** identity, the certificate chain, and whether this `preview`
channel build is the artifact intended for release were not examined.
