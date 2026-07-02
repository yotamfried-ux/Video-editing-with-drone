# Legacy route policy

Compatibility aliases are allowed only when they prevent breaking already-installed app builds or external integrations during a controlled migration window.

## Current aliases

| Alias route | Canonical route | Owner | Reason kept | Removal condition |
|---|---|---|---|---|
| `POST /api/operator/pipeline/run` | `POST /api/operator/pipeline/start` | Operator app pipeline contract | Older operator app builds may still call `/run`; current app code uses `/start`. | Remove only after the operator mobile app version that uses `/start` has been released and old builds are no longer supported or observable in logs. |

## Rules

1. New code must call the canonical route, not the alias.
2. Alias route files must not duplicate business logic. They should delegate to the canonical route.
3. Every alias must have an owner, reason kept, and removal condition in this document.
4. Every alias must be listed in `docs/operator-pipeline-contract.md` when it affects operator flows.
5. Removing an alias requires a PR that verifies no supported app build or integration still calls it.

## Review checklist

Before adding or keeping an alias, verify:

- The canonical route is documented.
- The alias delegates to the canonical route without a second implementation.
- Mobile code calls the canonical route.
- Deployment docs describe the alias as compatibility-only.
- Logs, release notes, or operator build support policy justify keeping it.
