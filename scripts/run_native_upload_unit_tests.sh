#!/usr/bin/env bash
# Runs the pure-JVM native background-upload tests without Gradle/Android SDK.
# Android-framework adapters (Worker, notification, module) are covered by the
# Gradle unit tests and the Android emulator qualification workflow instead.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/mobile/modules/sportreel-source-reader/android/src"
KT="${KOTLINC:-kotlinc}"
JARS="${NATIVE_TEST_JARS:?set NATIVE_TEST_JARS to a colon-separated list of junit, hamcrest and org.json jars}"
OUT="$(mktemp -d)"
PURE_MAIN=(
  BackgroundUploadJob BackgroundUploadStore UploadContracts MultipartUploadEngine
  HttpUploadApi UploadProgressSummary
)
FILES=()
for f in "${PURE_MAIN[@]}"; do
  p="$SRC/main/java/expo/modules/sportreelsourcereader/$f.kt"
  [ -f "$p" ] && FILES+=("$p")
done
FILES+=("$SRC"/test/java/expo/modules/sportreelsourcereader/*.kt)
"$KT" -nowarn -cp "$JARS" -d "$OUT" "${FILES[@]}"
CLASSES=$(cd "$OUT" && find . -name '*Test.class' | sed 's#^\./##; s#\.class$##; s#/#.#g' | grep -v '\$')
java -cp "$OUT:$JARS:$(dirname "$KT")/../lib/kotlin-stdlib.jar" org.junit.runner.JUnitCore $CLASSES
