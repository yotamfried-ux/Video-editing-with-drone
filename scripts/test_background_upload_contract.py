#!/usr/bin/env python3
"""Static contract for durable Android background uploads.

Asserts the architecture the approved design requires is actually present in the
repository: a WorkManager foreground worker with a network constraint, unique work
keyed by logical upload identity, no R2/service secrets on-device, the verified-batch
gate untouched, and an Android qualification workflow that exercises every lifecycle
and network transition with independent backend evidence.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KT = ROOT / "mobile/modules/sportreel-source-reader/android/src/main/java/expo/modules/sportreelsourcereader"


def read(path: str | Path) -> str:
    p = Path(path)
    return (p if p.is_absolute() else ROOT / p).read_text(encoding="utf-8")


def require(label: str, source: str, tokens: list[str]) -> None:
    missing = [t for t in tokens if t not in source]
    if missing:
        raise SystemExit(f"{label} missing: {missing}")


def forbid(label: str, source: str, patterns: list[str]) -> None:
    hits = [p for p in patterns if re.search(p, source, re.I)]
    if hits:
        raise SystemExit(f"{label} must not contain: {hits}")


def main() -> int:
    worker = read(KT / "BackgroundUploadWorker.kt")
    require("worker", worker, [
        "CoroutineWorker", "setForeground", "NetworkType.CONNECTED", "BackoffPolicy.EXPONENTIAL",
        "enqueueUniqueWork", "uniqueName(localId)", "ExistingWorkPolicy.KEEP", "resumeEligible",
    ])
    require("notification", read(KT / "UploadNotification.kt"), [
        "FOREGROUND_SERVICE_TYPE_DATA_SYNC", "UploadProgressSummary", "setOngoing(true)",
    ])
    require("manifest", read("mobile/modules/sportreel-source-reader/android/src/main/AndroidManifest.xml"), [
        'foregroundServiceType="dataSync"', "FOREGROUND_SERVICE_DATA_SYNC", "SystemForegroundService",
    ])

    # No R2 / Supabase service credentials anywhere in the native or JS upload path.
    for name in ("HttpUploadApi.kt", "AndroidAdapters.kt", "BackgroundUploadWorker.kt", "SportReelSourceReaderModule.kt"):
        forbid(f"native {name}", read(KT / name), [r"R2_SECRET", r"R2_ACCESS", r"SERVICE_ROLE", r"aws_secret", r"accountid"])
    forbid("backgroundUploadRuntime", read("mobile/src/features/operator/lib/backgroundUploadRuntime.ts"),
           [r"R2_SECRET", r"SERVICE_ROLE", r"aws_secret"])
    # The only credential that reaches native is the operator secret, kept in an Android Keystore-sealed vault.
    require("vault", read(KT / "AndroidAdapters.kt"), ["AndroidKeyStore", "AES/GCM/NoPadding"])

    engine = read(KT / "MultipartUploadEngine.kt")
    require("engine", engine, ["api.status(job)", "server_state_mismatch", "completedParts", "api.complete", "api.cleanup"])
    assert engine.index("api.status(job)") < engine.index("uploadMissingParts(localId, uploadId)"), \
        "engine must reconcile with server truth before uploading any part"

    # JS hands off to native, reserves the exact batch size, and keeps the verified-batch gate.
    client = read("mobile/src/features/operator/lib/backgroundUploadClient.ts")
    require("client", client, ["assignSharedUploadBatchId", "reserveBatchSlots", "enqueueBackgroundUpload", "hasIncompleteUploads"])
    pipeline = read("mobile/src/app/(operator)/pipeline.tsx")
    require("pipeline screen", pipeline, [
        "getBackgroundUploadClient", "reconcileBackgroundUploads", "AppState", "hasIncompleteUploads(uploadItems)",
        "/api/operator/pipeline/start",
    ])
    start_route = read("web-api/src/app/api/operator/pipeline/start/route.ts")
    require("server pipeline gate", start_route, ["assertUploadBatchReady", "resolveReadyUploadBatchId"])

    # Qualification workflow exercises every lifecycle + network transition with backend evidence.
    wf = read(".github/workflows/android-background-upload-qualification.yml")
    for scenario in (
        "foreground-baseline", "home-background", "screen-off", "process-death-resume",
        "relaunch-reconcile", "network-recovery", "worker-restart-retry",
    ):
        require(f"workflow scenario {scenario}", wf, [scenario])
    require("workflow", wf, [
        "android-emulator-runner", "run-bgupload-scenario.sh", "background_upload_evidence.py",
        "upload-artifact", "native-background-upload-check", "summary",
    ])
    runner = read("mobile/.maestro/background-upload/run-bgupload-scenario.sh")
    require("scenario runner", runner, [
        "KEYCODE_SLEEP", "KEYCODE_WAKEUP", "airplane-mode", "kill -9", "KEYCODE_HOME",
        "dumpsys notification", "part_put", "part_ack", "probe-gate-incomplete", "assert-gate-ready", "assert-final",
    ])
    for flow in ("01-background.yaml", "02-screen-off-resume.yaml", "03-process-restart.yaml", "04-network-recovery.yaml"):
        assert (ROOT / "mobile/.maestro/background-upload" / flow).exists(), f"missing Maestro flow {flow}"

    print("Durable Android background upload contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
