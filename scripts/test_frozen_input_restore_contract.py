#!/usr/bin/env python3
"""Behavioural contract for manifest-driven RAW/PROCESSED reconciliation."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.r2_batch_restore import FrozenInputError, reconcile_frozen_inputs  # noqa: E402

BATCH = "batch_2026-10-03T12-19-52_ttgvat95"
OTHER = "batch_other"


class FakeStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.calls: list[tuple] = []
        self.fail_copy_size = False

    def head(self, key):
        return {"ContentLength": len(self.objects[key])} if key in self.objects else None

    def list(self, prefix):
        self.calls.append(("list", prefix))
        return [{"Key": k, "Size": len(v)} for k, v in sorted(self.objects.items()) if k.startswith(prefix)]

    def copy(self, src, dst):
        self.calls.append(("copy", src, dst))
        assert dst not in self.objects, "restore must never overwrite RAW"
        self.objects[dst] = self.objects[src][:-1] if self.fail_copy_size else self.objects[src]

    def delete(self, key):
        self.calls.append(("delete", key))
        del self.objects[key]

    def sha256(self, key):
        return hashlib.sha256(self.objects[key]).hexdigest()


def build(n=24, location="processed"):
    store = FakeStore()
    manifest = []
    for i in range(n):
        name = f"2026-10-03T12-19-53_DJI_{i:04d}_D.MP4"
        data = (f"video-{i}-" * (i + 3)).encode()
        key = f"raw/{BATCH}/{name}"
        manifest.append({
            "upload_id": f"u{i}", "storage_key": key, "source_filename": name,
            "source_size_bytes": len(data), "verified_size_bytes": len(data),
        })
        loc = key if location == "raw" else key.replace("raw/", "processed/", 1)
        store.objects[loc] = data
    return store, manifest


def snapshot(store):
    return dict(store.objects)


def test_all_in_raw_is_noop():
    store, manifest = build(location="raw")
    before = snapshot(store)
    report = reconcile_frozen_inputs(store, manifest, BATCH)
    assert report.summary()["in_raw"] == 24 and report.restored == 0 and report.verified == 24
    assert snapshot(store) == before
    assert not [c for c in store.calls if c[0] in {"copy", "delete"}]


def test_all_in_processed_restored_exactly():
    store, manifest = build(location="processed")
    originals = {m["storage_key"]: store.objects[m["storage_key"].replace("raw/", "processed/", 1)] for m in manifest}
    report = reconcile_frozen_inputs(store, manifest, BATCH)
    assert report.restored == 24 and report.verified == 24
    assert {k for k in store.objects if k.startswith("raw/")} == set(originals)
    assert not [k for k in store.objects if k.startswith("processed/")]
    assert all(store.objects[k] == v for k, v in originals.items())


def test_mixed_raw_and_processed():
    store, manifest = build(location="processed")
    for m in manifest[:10]:
        store.objects[m["storage_key"]] = store.objects.pop(m["storage_key"].replace("raw/", "processed/", 1))
    report = reconcile_frozen_inputs(store, manifest, BATCH)
    assert (report.restored, report.verified) == (14, 24)
    assert len([k for k in store.objects if k.startswith("raw/")]) == 24


def test_missing_everywhere_is_hard_failure_and_changes_nothing():
    store, manifest = build(location="processed")
    del store.objects[manifest[5]["storage_key"].replace("raw/", "processed/", 1)]
    before = snapshot(store)
    try:
        reconcile_frozen_inputs(store, manifest, BATCH)
    except FrozenInputError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("missing source must fail closed")
    assert snapshot(store) == before, "nothing may be restored when any input is unrecoverable"


def test_size_mismatch_in_processed_and_raw_fail():
    for loc in ("processed", "raw"):
        store, manifest = build(location=loc)
        key = manifest[3]["storage_key"] if loc == "raw" else manifest[3]["storage_key"].replace("raw/", "processed/", 1)
        store.objects[key] += b"x"
        before = snapshot(store)
        try:
            reconcile_frozen_inputs(store, manifest, BATCH)
        except FrozenInputError as exc:
            assert "size_mismatch" in str(exc)
        else:
            raise AssertionError("size mismatch must fail closed")
        assert snapshot(store) == before


def test_conflicting_raw_never_replaced_by_processed():
    store, manifest = build(location="processed")
    key = manifest[0]["storage_key"]
    store.objects[key] = b"other bytes"  # wrong object already in RAW
    try:
        reconcile_frozen_inputs(store, manifest, BATCH)
    except FrozenInputError:
        pass
    else:
        raise AssertionError("conflicting raw object must fail closed")
    assert store.objects[key] == b"other bytes"


def test_unrelated_processed_and_other_batch_untouched():
    store, manifest = build(location="processed")
    store.objects["processed/legacy_flat.mp4"] = b"legacy"
    store.objects[f"processed/{BATCH}/stray_not_in_manifest.mp4"] = b"stray"
    store.objects[f"processed/{OTHER}/a.mp4"] = b"A"
    store.objects[f"raw/{OTHER}/b.mp4"] = b"B"
    foreign = {k: v for k, v in store.objects.items() if "legacy" in k or OTHER in k or "stray" in k}
    report = reconcile_frozen_inputs(store, manifest, BATCH)
    assert report.processed_not_in_manifest == 1
    for k, v in foreign.items():
        assert store.objects[k] == v
    assert all(not (c[0] in {"copy", "delete"} and (OTHER in c[1] or "legacy" in c[1] or "stray" in c[1])) for c in store.calls)
    assert all(c[1].startswith((f"raw/{BATCH}/", f"processed/{BATCH}/")) for c in store.calls if c[0] == "list")


def test_unexpected_raw_video_fails_closed():
    store, manifest = build(location="raw")
    store.objects[f"raw/{BATCH}/intruder.mp4"] = b"intruder"
    try:
        reconcile_frozen_inputs(store, manifest, BATCH)
    except FrozenInputError as exc:
        assert "unexpected" in str(exc)
    else:
        raise AssertionError("unexpected raw input must fail closed")


def test_idempotent_second_run():
    store, manifest = build(location="processed")
    first = reconcile_frozen_inputs(store, manifest, BATCH)
    after_first = snapshot(store)
    second = reconcile_frozen_inputs(store, manifest, BATCH)
    assert first.restored == 24 and second.restored == 0 and second.summary()["in_raw"] == 24
    assert snapshot(store) == after_first


def test_audit_mode_is_read_only():
    store, manifest = build(location="processed")
    before = snapshot(store)
    report = reconcile_frozen_inputs(store, manifest, BATCH, restore=False)
    assert report.summary()["restorable_from_processed"] == 24
    assert snapshot(store) == before


def test_bad_copy_is_rolled_back_and_processed_kept():
    store, manifest = build(n=3, location="processed")
    store.fail_copy_size = True
    try:
        reconcile_frozen_inputs(store, manifest, BATCH)
    except FrozenInputError:
        pass
    else:
        raise AssertionError("short copy must fail")
    assert len([k for k in store.objects if k.startswith("processed/")]) == 3
    assert not [k for k in store.objects if k.startswith("raw/")]


def test_sha256_identity_enforced():
    store, manifest = build(n=3, location="processed")
    good = {m["storage_key"]: hashlib.sha256(store.objects[m["storage_key"].replace("raw/", "processed/", 1)]).hexdigest() for m in manifest}
    report = reconcile_frozen_inputs(store, manifest, BATCH, verify_sha256=True, expected_sha256=good)
    assert report.restored == 3
    store2, manifest2 = build(n=3, location="processed")
    bad = dict(good)
    bad[manifest2[1]["storage_key"]] = "0" * 64
    before = snapshot(store2)
    try:
        reconcile_frozen_inputs(store2, manifest2, BATCH, verify_sha256=True, expected_sha256=bad)
    except FrozenInputError as exc:
        assert "content verification" in str(exc)
    else:
        raise AssertionError("sha mismatch must fail")
    assert snapshot(store2) == before


def test_manifest_validation():
    store, manifest = build(n=2, location="raw")
    cases = {
        "foreign batch": [{**manifest[0], "storage_key": f"raw/{OTHER}/x.mp4"}],
        "duplicate": [manifest[0], manifest[0]],
        "unverified": [{**manifest[0], "verified_size_bytes": 1}],
        "empty": [],
    }
    for label, bad in cases.items():
        try:
            reconcile_frozen_inputs(store, bad, BATCH)
        except FrozenInputError:
            continue
        raise AssertionError(f"{label} manifest must be rejected")
    try:
        reconcile_frozen_inputs(store, manifest, "")
    except FrozenInputError:
        pass
    else:
        raise AssertionError("explicit batch id is mandatory")


def _flat(store, manifest, where="raw"):
    for m in manifest:
        key = m["storage_key"]
        name = key.rsplit("/", 1)[-1]
        for loc in (key, key.replace("raw/", "processed/", 1)):
            if loc in store.objects:
                store.objects[f"{where}/{name}"] = store.objects.pop(loc)
    return {m["storage_key"]: hashlib.sha256(store.objects[f"{where}/{m['storage_key'].rsplit('/', 1)[-1]}"]).hexdigest() for m in manifest}


def test_legacy_flat_layout_recovered_only_with_sha_proof():
    store, manifest = build(location="processed")
    shas = _flat(store, manifest)
    # default behaviour never goes looking in the flat namespace
    try:
        reconcile_frozen_inputs(store, manifest, BATCH)
    except FrozenInputError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("flat layout must not be touched unless explicitly requested")
    report = reconcile_frozen_inputs(store, manifest, BATCH, recover_legacy_flat=True, expected_sha256=shas)
    assert report.restored == 24 and report.verified == 24
    assert {k for k in store.objects if k.startswith("raw/")} == {m["storage_key"] for m in manifest}


def test_legacy_flat_without_identity_or_with_wrong_bytes_fails_closed():
    store, manifest = build(n=4, location="processed")
    shas = _flat(store, manifest)
    before = snapshot(store)
    try:
        reconcile_frozen_inputs(store, manifest, BATCH, recover_legacy_flat=True)
    except FrozenInputError:
        pass
    else:
        raise AssertionError("flat source without durable identity must fail")
    bad = dict(shas)
    bad[manifest[2]["storage_key"]] = "f" * 64
    try:
        reconcile_frozen_inputs(store, manifest, BATCH, recover_legacy_flat=True, expected_sha256=bad)
    except FrozenInputError as exc:
        assert "content verification" in str(exc)
    else:
        raise AssertionError("flat source with wrong bytes must fail")
    assert snapshot(store) == before


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"{len(tests)} frozen-input restore checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
