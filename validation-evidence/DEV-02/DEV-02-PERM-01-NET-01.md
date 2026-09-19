# DEV-02 / PERM-01 / NET-01 — OS-version matrix, permissions, offline behaviour

**Results: DEV-02 PASS (emulator scope) · PERM-01 PASS · NET-01 PARTIAL**

| Field | Value |
| --- | --- |
| Executed | 2026-09-19T10:28Z – 10:33Z |
| Workflow run | [35437507304](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35437507304) |
| Jobs | android-30 `105882568604`, android-33 `105882568490`, android-35 `105882568644` — all success |
| Harness commit | `aa8612e` |
| APK | EAS build `3884d669-850c-4b76-bba5-5e57ffcd2245`, SHA-256 `997c3b4c…daa47789`, built from `356d581` |
| Evidence | `validation-evidence/DEV-02/api-{30,33,35}-run-35437507304/` |

A prior attempt (run [35437154481](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35437154481))
is retained as BEFORE evidence — see "Harness defects found and fixed".

---

## DEV-02 — Behaviour across Android versions — PASS (emulator scope)

| API | Android | Install | Launch | Cold start | Login rendered |
| --- | --- | --- | --- | --- | --- |
| 30 | **11** (scoped storage enforced) | `Success` | `Status: ok` | **1 651 ms** | yes |
| 33 | **13** (granular media permissions) | `Success` | `Status: ok` | **3 014 ms** | yes |
| 35 | **15** (current target) | `Success` | `Status: ok` | **4 903 ms** | yes |

The exact production APK installs, launches and renders its login surface on all
three OS generations. All frames measured as genuinely rendered.

Cold start rises monotonically with API level (1.65 s → 3.01 s → 4.90 s, ~3×
across the range). Single samples on a shared runner, so this is an observation
worth tracking, not a benchmark.

**Scope limit:** emulator only. Per the brief this is not transferable to
physical-device readiness (DEV-01/REALDEV-01 remain BLOCKED, BLOCKER-005).

---

## PERM-01 — Declared and granted permissions — PASS

Read from `dumpsys package com.sportreel.app` on the installed APK. Identical
across all three OS versions.

**Android permissions the app requests:**

```
android.permission.INTERNET                  granted=true
android.permission.ACCESS_NETWORK_STATE      granted=true
android.permission.CAMERA
android.permission.RECORD_AUDIO
android.permission.READ_EXTERNAL_STORAGE
android.permission.WRITE_EXTERNAL_STORAGE
android.permission.POST_NOTIFICATIONS
android.permission.RECEIVE_BOOT_COMPLETED    granted=true
android.permission.VIBRATE                   granted=true
android.permission.WAKE_LOCK
android.permission.SYSTEM_ALERT_WINDOW
android.permission.DETECT_SCREEN_CAPTURE     granted=true (API 35)
android.permission.USE_BIOMETRIC
android.permission.USE_FINGERPRINT           granted=true
com.google.android.c2dm.permission.RECEIVE   granted=true
com.sportreel.app.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION
```

Plus ~15 third-party launcher *badge* permissions (Samsung, Huawei, Oppo, HTC,
Sony, Apex, Nova…), which come from the notification-badge library, not from
SportReel's own manifest — `mobile/app.json` declares only six.

**No runtime permission is granted at first launch**, which is correct: the app
reaches its login screen without prompting for camera, microphone or storage.

### Finding examined and dismissed: legacy storage permissions

The manifest declares `READ_EXTERNAL_STORAGE` / `WRITE_EXTERNAL_STORAGE` and
**no** `READ_MEDIA_VIDEO` / `READ_MEDIA_IMAGES`. On Android 13+ the legacy
permissions are inert, so this initially looks like a defect that would break
media selection on API 33+.

It is **not** a defect. `SportReelSourceReaderModule.kt` accepts only
`content://` URIs:

```kotlin
if (uri.scheme != ContentResolver.SCHEME_CONTENT) {
  throw IllegalArgumentException("source_uri_invalid: only content:// SD/USB sources are supported")
}
```

and reads through `ContentResolver`. That is the Storage Access Framework path,
where the system document picker grants access per-URI and **no storage
permission is required at all**, on any API level. The design is correct for
Android 13+.

The legacy permissions therefore appear **vestigial**. Recorded as GAP-011 (P2,
hygiene). Note this reasoning is from code plus manifest, not from an observed
media selection — that still needs a physical device (BLOCKER-005).

`SYSTEM_ALERT_WINDOW` (draw-over-other-apps) is also declared and was not
explained by anything observed; flagged in GAP-011 as worth confirming.

---

## NET-01 — Offline behaviour — PARTIAL

Method: device taken fully offline (`svc wifi disable`, `svc data disable`,
`airplane_mode_on=1` — confirmed by the ✈ status-bar icon in the captures),
then the real Sign In control driven at its live hit-tested position, then
connectivity restored.

| API | Error surfaced to the user | App stayed foreground | Recovered on reconnect |
| --- | --- | --- | --- |
| 30 | **"Network request failed"** | yes | yes — login screen restored |
| 33 | **not observed** | yes | yes — login screen restored |
| 35 | **"Network request failed"** | yes | yes — login screen restored |

**What is established.** The app does not crash offline, does not hang, stays
foreground, and on API 30 and 35 it tells the user truthfully that the network
request failed. It does **not** report a false success. On reconnect all three
return to a usable login screen.

**Why PARTIAL.** On API 33 no error text appeared in either the UI dump or the
screenshot at the same 12-second observation point where API 30 and 35 both
showed one. The `api33-02-offline.png` capture shows the filled form, airplane
mode active, and **no error message anywhere**. This is either a transient
banner that had already dismissed, or a genuine inconsistency where the API 33
path leaves the user with no feedback. One observation cannot distinguish those,
so NET-01 is not marked PASS. Recorded as GAP-012.

**Harness caveat on the input.** `KEYCODE_TAB` did not move focus from the email
field to the password field, so both strings landed in the email field
(`offline-probe@example.invalidnot-a-real-password`, visible in the captures).
The submitted form was therefore malformed. This does not weaken the finding —
with the network off, "Network request failed" is the correct and truthful
outcome regardless of payload — but a clean offline test with a well-formed
credential pair has not been run. Whether TAB *should* traverse fields for
hardware-keyboard users is a separate, unassessed question.

---

## Harness defects found and fixed during this experiment

Both were found by running, and both BEFORE states are preserved in run
`35437154481`.

**1. The KVM enablement step is not deterministic.** The `android-30` job failed
that step outright while `android-33` and `android-35` passed on identical
configuration. Fixed by applying the udev rule, `usermod -aG kvm`, and a direct
`chmod 666` together, then verifying with retries. All three jobs passed
afterwards. Recorded as an amendment to GAP-001.

**2. A system ANR dialog silently invalidated the probe.** A
*"Pixel Launcher isn't responding"* dialog appeared over the app and swallowed
every tap. All three UI dumps in that run were byte-identical 4 189-byte
captures of the **dialog**, not of SportReel. SportReel itself was healthy
underneath — it rendered correctly behind the dialog and `dumpsys` confirmed
`topResumedActivity=ActivityRecord{… com.sportreel.app/.MainActivity}`.

Critically, the harness would have reported this as a result. The matrix now
detects a system ANR, dismisses it via *Wait*, refuses any UI dump still
containing one, and emits `NET01_INTERACTION_VALID` so an invalidated probe
cannot be mistaken for a finding. Recorded as GAP-013.
