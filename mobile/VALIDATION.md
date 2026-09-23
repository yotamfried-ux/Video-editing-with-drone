# Mobile validation

Every change under `mobile/` must pass:

```bash
npm ci
npm run type-check
```

GitHub Actions runs the same check for mobile pull requests through `.github/workflows/mobile-check.yml`.

## UPL-01 Android upload E2E (Maestro)

The operator gallery-upload journey is driven by Maestro flows in
`mobile/.maestro/upl01/` and executed on an API-35 emulator by
`.github/workflows/upl-01-android-app-upload-e2e.yml`:

| Flow | Kind | Asserted semantics |
|---|---|---|
| `00-seed-media` | setup | seeds the per-run MP4 once via `addMedia` |
| `01-no-operator-secret` | negative | `Some uploads failed`; item `Failed` with `Operator secret not set`; no backend row |
| `02-picker-cancelled` | negative | silent no-op; no upload row/alert; upload button idle; no backend row |
| `03-gallery-upload` | positive | `Uploaded to queue`; item `Verified · 100%` |

UI results are only half the evidence. `scripts/upl01_backend_evidence.py` then
requires exactly one `source_uploads` row for the fixture since the run window
opened (verified, `single_put`, declared = verified = fixture bytes) and a
production verify-API HEAD of the exact R2 object.

Rules:

- Target elements by `testID` or visible text, never coordinates or `sleep`.
- The operator secret reaches flows only via the runtime `MAESTRO_OPERATOR_SECRET` env var.
- `EXPO_PUBLIC_UPL01_OPERATOR_BYPASS` is a validation-only entry point, not an auth mechanism, and must never appear in an EAS profile.
- Media fixtures are generated per run and never committed.

Fast local checks (no device needed):

```bash
python scripts/test_upl01_maestro_contract.py
for f in mobile/.maestro/upl01/*.yaml mobile/.maestro/upl01/subflows/*.yaml; do maestro check-syntax "$f"; done
```

With an emulator or device visible to `adb`, the Maestro MCP (`claude mcp add maestro -- maestro mcp`) can be used to explore interactively before encoding a flow.
