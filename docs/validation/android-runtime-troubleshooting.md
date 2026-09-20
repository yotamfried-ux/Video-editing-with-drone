# Android validation troubleshooting log

This document records failures encountered while qualifying the SportReel Android runtime validation path, their causes, and the fixes that should be reused instead of rediscovering them.

## Scope and invariants

The runtime suite validates the APK built from product commit `b76cdd5e9434d5f2f681cc5a2f485f247996cda0`. Once that APK was built and checkpointed, subsequent harness-only changes must restore the provenance-pinned APK cache instead of rebuilding the product. Previously passed experiments should not be repeated unless their product assumptions changed.

Authentication remains production-like: email confirmation is not disabled. Test-only automation uses Supabase's admin API with a repository secret and deletes its temporary user in an `always()` cleanup step. Secrets and generated passwords must never be committed or printed.

## Incident history

### 1. Older cached APK did not prove current main

An earlier Android runtime run used an APK pinned to an older product SHA. Its APP-01/APP-02 results were useful historical evidence but could not establish the state of current main.

**Resolution:** pin `TESTED_SHA` to the current product commit, rotate the cache key, build once, record APK provenance, and save that exact APK as the checkpoint. Run 35500812134 established the current-main baseline successfully.

### 2. Initial UI dump race in APP-03

Run 35501707890 failed before login because the harness attempted to inspect `APP-03/login.xml` before a successful UIAutomator dump/pull had created the file.

**Resolution:** UI polling must tolerate a missing dump file. Create destination directories first and only grep after confirming the XML file exists. A missing first dump is a harness timing condition, not a product failure.

### 3. Reconstructing credentials from an earlier run was unsafe and unreliable

The first authenticated-journey attempt depended on credentials generated in a previous workflow. The password had been generated from a separate timestamp and was intentionally not persisted, so reconstructing it was not reliable. A transient workflow revision also embedded test credentials directly in repository text.

**Resolution:** remove the unsafe transient workflow, delete the associated temporary Supabase user, and never commit test passwords. Each authenticated test run now creates its own fixture.

### 4. Email-confirmation wait made the emulator run depend on an external manual action

Run 35502006331 successfully reached signup and the confirmation-email state, but the emulator eventually failed because the confirmation link was not opened within the workflow's wait window. APP-02 had already separately proven the real signup -> email delivery -> confirmation path, so repeating that dependency for APP-03+ added cost and flakiness without adding coverage.

**Resolution:** keep real email confirmation enabled for the product and APP-02 evidence. For APP-03+ fixture setup, create an already-confirmed disposable user through the Supabase Admin API. This separates authentication-flow coverage from test-fixture provisioning.

### 5. GitHub Actions initially lacked Supabase admin credentials

The automated fixture design requires privileged Supabase Admin API access, but the repository initially had no suitable Actions secret.

**Resolution:** provision `SUPABASE_SERVICE_ROLE_KEY` as a GitHub Actions repository secret. The workflow consumes it only in fixture creation/cleanup steps. It is never written to artifacts or source.

### 6. Fixture outputs were not propagated into the emulator action

Run 35502768102 proved that the repository secret worked: the confirmed Supabase user was created successfully and cleanup deleted it successfully. The Android journey nevertheless stopped with `TEST_EMAIL: unbound variable`.

**Root cause:** `TEST_EMAIL` and `TEST_PASSWORD` were supplied to the step that generated `journey.sh`, but the variables are expanded when that script executes. The separate `android-emulator-runner` step did not have those environment variables.

**Resolution:** pass the fixture outputs as environment variables directly to the `Run targeted journey` step:
- `TEST_EMAIL: ${{ steps.test-user.outputs.email }}`
- `TEST_PASSWORD: ${{ steps.test-user.outputs.password }}`

The temporary user cleanup remains `if: always()`, so a failed emulator experiment does not leave test accounts behind.

## Operational rules

1. Build once, reuse the exact provenance-pinned APK checkpoint while `TESTED_SHA` is unchanged.
2. After a harness failure, rerun only the smallest experiment set affected by that failure.
3. Distinguish harness failures from product failures. A missing XML dump, unavailable test credential, or environment propagation bug is not evidence that SportReel failed.
4. Never place service-role keys, access/refresh tokens, passwords, or other credentials in source, logs, screenshots, or artifacts.
5. Keep Supabase email confirmation enabled. Use admin-created confirmed users only as disposable prerequisites for tests whose subject is post-confirmation behavior.
6. Delete temporary auth users even when the test fails.
7. Preserve evidence artifacts and run IDs so each conclusion can be traced to the exact workflow and product SHA.

## Key evidence runs

- `35500812134`: current-main APP-01/APP-02 baseline; success; exact APK checkpoint established.
- `35501707890`: APP-03 harness failed on initial UI-dump race.
- `35502006331`: signup reached email-confirmation wait; demonstrated why APP-03+ should not depend on manual email confirmation.
- `35502768102`: Supabase admin fixture creation and cleanup succeeded; emulator journey exposed missing environment propagation.

Update this document whenever a new validation failure reveals a reusable lesson or changes the runbook.

### 7. UIAutomator dump lost React Native nodes during keyboard transition

Run `35502998526` got past fixture creation and environment propagation. Evidence contained a valid `APP-03/login.xml` with both EditText controls, followed by `APP-03/login-email.xml` whose hierarchy contained the app's native root/FrameLayout but no React Native accessibility nodes. The failure happened immediately after typing the email and re-dumping the UI while the soft keyboard/window resize was transitioning. The harness then could not discover the password field and exited under `set -e`.

**Resolution:** do not require a second UIAutomator discovery between the two login fields. Capture both EditText bounds from the stable initial login dump, type email and password using those known controls, dismiss the keyboard, and only then capture another evidence dump. This removes a harness-only accessibility timing dependency without changing product code.

### 8. Pre-keyboard password coordinates became stale after the keyboard opened

Run `35503417156` produced three APP-03 XML artifacts. The initial login dump showed separate Email and Password controls. The post-entry evidence showed the Email field containing the email followed by the beginning of the generated password, and the result showed `Invalid login credentials`. This proves the second absolute-coordinate tap landed back in Email after Android panned/resized the window for the soft keyboard; the credentials themselves were not rejected because of Supabase fixture provisioning.

**Resolution:** use the stable initial coordinate only to focus Email. After entering Email, send Android TAB/next-focus (`KEYCODE_TAB`) to move semantically to Password, type the password into the focused control, and then dismiss the keyboard. Do not reuse pre-keyboard absolute Y coordinates after the viewport changes.

### 9. Android TAB was not reliable for the React Native login fields

Run `35503974760` reached APP-03, but the evidence immediately before submission shows both login inputs empty. The result then shows Supabase's `missing email or phone`. The test-user outputs were present in the job environment, so fixture creation and environment propagation were not the cause.

The changed behavior was the TAB-based focus transition. For these React Native TextInputs it did not provide a reliable next-field transition, and the entered form state was not present when Sign In was submitted.

**Resolution:** remove TAB-based navigation. After Email entry, let the keyboard/window transition settle, obtain a fresh transient UI tree until both inputs are visible, and target Password using its current bounds. Do not archive that transient tree because input-state dumps are not needed as durable evidence. Then dismiss the keyboard and capture only the navigation evidence required by APP-03.

### 10. ADB text entry started before Email focus was stable

Run `35504511461` proved the post-keyboard Password rediscovery works: the password field contained the expected masked value. However, the submitted Email was `ortreel.e2e+35504511461@example.com` instead of the generated address beginning with `sportreel...`. Supabase therefore correctly returned `Invalid login credentials`.

The missing leading characters show that `adb shell input text` began while the React Native Email field was still completing its focus transition after the tap. This is a harness timing defect, not an Auth/product defect.

**Resolution:** make the shared coordinate typing helper wait briefly after the tap before sending text. This applies the stabilization at the actual interaction boundary and also protects later profile-name entry without rebuilding the APK or repeating already-passed setup tests.

### 11. APP-06 expected the wrong post-sign-out screen

Run `35505056760` successfully completed APP-03, APP-04, and APP-05. Evidence shows valid credentials, first-login profile completion, Discover navigation, the saved name `SportReel_Validation`, and authenticated session persistence after force-stop/relaunch. APP-06 then successfully signed out, but the harness incorrectly waited for `Welcome Back` immediately.

The app's actual signed-out Profile state is intentional: it displays `Sign in to view your profile` with `Sign In` and `Create Account` actions. The failure was therefore an incorrect test expectation, not a product/auth failure.

**Resolution:** APP-06 now asserts the unauthenticated Profile state after Sign Out, taps the visible `Sign In` action, and only then asserts `Welcome Back`. No product change or APK rebuild is required.


### 12. APP-06 tapped the child text label instead of the semantic Profile tab

Run `35506003382` produced PASS evidence for APP-03, APP-04, and APP-05. Its APP-06 profile dump still showed the Discover screen and contained no `Sign Out` control, so the failure occurred before sign-out. The earlier ADB port-5037 messages were transient emulator-startup diagnostics; they are not the root cause because the same run subsequently completed APP-03 through APP-05.

The harness targeted the small child node whose visible text is `Profile`. The accessibility hierarchy also exposes the full tab as a larger semantic node with a content description containing `Profile`. Android UI Automator explicitly supports selecting elements by content description and clickable state; targeting the semantic tab is more robust than tapping the child label's coordinates.

**Resolution:** add a content-description-based tap helper and use the full `Profile` tab accessibility node for tab navigation. Keep text-based targeting for controls whose text node is itself the intended target. No product code or APK rebuild is required.


### 13. Semantic Profile selector had an over-escaped bounds parser

Run `35506505455` produced PASS evidence for APP-03 and APP-04, then stopped before creating APP-05 evidence. The saved Discover hierarchy contains a clickable semantic node with content description `Profile` and bounds `[540,1731][1080,1857]`. The new selector matched that node, but its dedicated `sed` expression had been written with doubled backslashes inside a single-quoted shell expression, so it returned no coordinates and `tap_desc` failed under `set -e` before issuing the tap.

Android's official tooling documents accessibility `contentDesc`, clickable interactions, and element bounds as appropriate UI properties for automation, so the semantic-node approach remains the preferred method over reverting to the smaller child text node. The defect was only in our shell parser.

**Resolution:** keep semantic Profile targeting and correct the bounds parser to use the same proven escaping as the existing text-node `bounds()` helper. No product change, APK rebuild, or repetition of the APP-01/APP-02 baseline is required.


### 14. Parent semantic-node center was not a reliable tab activation point

Run `35506789889` passed APP-03 and APP-04, then the APP-05 profile capture still showed Discover. This isolates the failure to the Profile-tab interaction introduced by the semantic-parent targeting change; the application had not failed authentication or profile completion.

Android's official interaction guidance says to inspect the current layout, use an element's supported interactions, and inject `adb shell input tap` at the target element's center/bounds. It also says to wait and re-read layout when content may still be changing. The earlier child-label tap had already succeeded in this same journey before the relaunch case, so replacing both calls with the parent node widened the change unnecessarily.

**Resolution:** restore the proven visible `Profile` label target for the normal Discover-to-Profile transition. For the post-force-stop transition, first allow the relaunched UI to settle, take a fresh transient layout, and only then tap the visible Profile label. Keep the subsequent screen assertion as the authority. No product change or APK rebuild is required.
