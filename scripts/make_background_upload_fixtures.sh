#!/usr/bin/env bash
# Creates N uniquely named, uniquely sized MP4 fixtures (real MP4 header + payload padding) for the
# Android background-upload qualification. Sizes exceed several multipart parts (16 MiB default) so an
# interruption always lands mid-multipart. Usage: make_background_upload_fixtures.sh DIR SCENARIO COUNT RUN_ID
set -euo pipefail
DIR="${1:?fixture dir required}"; SCENARIO="${2:?scenario required}"; COUNT="${3:-3}"; RUN_ID="${4:-local}"
BASE_MIB="${BGQ_FIXTURE_MIB:-100}"
mkdir -p "${DIR:?}"
find "${DIR:?}" -maxdepth 1 -name '*.mp4' -type f -delete
SEED=$(printf '%s' "$SCENARIO$RUN_ID" | cksum | cut -d' ' -f1)
for i in $(seq 1 "$COUNT"); do
  out="$DIR/bgq_${SCENARIO}_${RUN_ID}_${i}.mp4"
  freq=$((400 + (SEED % 400) + i * 70))
  ffmpeg -hide_banner -loglevel error -y -f lavfi -i "testsrc=size=320x180:rate=30" \
    -f lavfi -i "sine=frequency=${freq}:sample_rate=48000" -t 3 -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "$out"
  target=$(( (BASE_MIB + i * 4) * 1024 * 1024 + (SEED % 9973) + i * 1237 ))
  have=$(stat -c %s "$out")
  head -c $((target - have)) /dev/urandom >> "$out"
  test "$(stat -c %s "$out")" -eq "$target"
  echo "$(basename "$out") $target"
done
