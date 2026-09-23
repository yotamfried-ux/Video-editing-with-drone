# Mobile validation

Every change under `mobile/` must pass:

```bash
npm ci
npm run type-check
```

GitHub Actions runs the same check for mobile pull requests through `.github/workflows/mobile-check.yml`.

## UPL-01 Android upload E2E (Maestro)

The operator gallery-upload journey is driven by Maestro flows in
`mobile/.maestro/upl01/` and executed by
`.github/workflows/upl-01-android-app-upload-e2e.yml`. The APK is prepared once,
then the independent behavioral scenarios run concurrently on isolated API-35
emulators (`max-parallel: 3`) rather than sharing one emulator serially:

| Flow | Kind | Asserted semantics |
|---|---|---|
| `00-seed-media` | setup | seeds the per-run MP4 once via `addMedia` |
| `01-no-operator-secret` | negative | `Some uploads failed`; item `Failed` with `Operator secret not set`; no backend row |
| `02-picker-cancelled` | negative | silent no-op; no upload row/alert; upload button idle; no backend row |
| `03-gallery-upload` | positive | `Uploaded to queue`; item `Verified · 100%` |

Each matrix worker generates a different fixture byte size, seeds it once, and
keeps separate evidence. That makes concurrent backend correlation deterministic:
the two negative workers require **zero** matching `source_uploads` rows, while
the positive worker requires exactly one verified `single_put` row whose
declared/verified sizes equal its fixture, plus a production verify-API HEAD of
the exact R2 object.

The final summary job passes only when APK preparation and all three parallel
scenario jobs pass.

Rules:

- Target elements by `testID` or visible text, never coordinates or `sleep`.
- The operator secret reaches flows only via the runtime `MAESTRO_OPERATOR_SECRET` env var.
- `EXPO_PUBLIC_UPL01_OPERATOR_BYPASS` is a validation-only entry point, not an auth mechanism, and must never appear in an EAS profile.
- Media fixtures are generated per scenario/run and never committed.
- Separate workflow runs remain serialized against the production backend; only isolated scenarios inside one run execute concurrently.

Fast local checks (no device needed):

```bash
python scripts/test_upl01_maestro_contract.py
for f in mobile/.maestro/upl01/*.yaml mobile/.maestro/upl01/subflows/*.yaml; do maestro check-syntax "$f"; done
```

With an emulator or device visible to `adb`, the Maestro MCP (`claude mcp add maestro -- maestro mcp`) can be used to explore interactively before encoding a flow.
