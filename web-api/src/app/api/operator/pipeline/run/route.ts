// Backward-compatible alias for older operator app builds.
//
// Canonical route: POST /api/operator/pipeline/start
// Compatibility owner: Operator app pipeline contract
// Removal condition: remove only after the operator mobile app build that calls
// /api/operator/pipeline/start has been released and older /run callers are no
// longer supported or observable in logs.
//
// Do not add business logic here. This file must delegate to the canonical
// route so /run and /start cannot drift.
export { POST } from '../start/route';
