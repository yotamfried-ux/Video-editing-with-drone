#!/usr/bin/env python3
"""Unit tests for the pure evidence checks in background_upload_evidence.py."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import background_upload_evidence as ev  # noqa: E402

MIB = 1024 * 1024


def row(i, **kw):
    base = {
        "id": f"u{i}", "client_upload_id": f"bg_{i:040d}", "batch_id": "batch_x", "storage_key": f"raw/batch_x/{i}_clip{i}.mp4",
        "source_filename": f"clip{i}.mp4", "status": "verified", "upload_protocol": "r2_multipart_v1",
        "source_size_bytes": (40 + i) * MIB, "verified_size_bytes": (40 + i) * MIB, "expected_part_count": 3,
        "completed_part_count": 3, "local_cleanup_status": "confirmed",
    }
    base.update(kw)
    return base


def parts(i, nums=(1, 2, 3)):
    return [{"source_upload_id": f"u{i}", "part_number": n} for n in nums]


def good():
    rows = [row(i) for i in range(3)]
    p = {r["id"]: parts(int(r["id"][1:])) for r in rows}
    objs = {r["storage_key"]: r["source_size_bytes"] for r in rows}
    return rows, p, objs


class PartLog(unittest.TestCase):
    def test_clean_run_has_no_violation(self):
        lines = ["I SportReelBgUpload: part_put a 1/3", "I SportReelBgUpload: part_ack a 1/3", "part_put a 2/3", "part_ack a 2/3"]
        r = ev.analyze_part_log(lines)
        self.assertEqual(r["resent_acknowledged"], [])
        self.assertEqual(r["acks"], {"a": [1, 2]})

    def test_unacknowledged_part_may_be_resent(self):
        r = ev.analyze_part_log(["part_put a 1/3", "part_put a 1/3", "part_ack a 1/3"])
        self.assertEqual(r["resent_acknowledged"], [])

    def test_acknowledged_part_resent_is_flagged(self):
        r = ev.analyze_part_log(["part_put a 1/3", "part_ack a 1/3", "part_put a 1/3"])
        self.assertEqual(r["resent_acknowledged"], [("a", 1)])

    def test_resume_reconcile_lines_are_counted(self):
        r = ev.analyze_part_log(["reconcile a server_parts=[1, 2] status=uploading", "reconcile a server_parts=[] status=uploading"])
        self.assertEqual(r["reconciles"], 2)


class Final(unittest.TestCase):
    def test_exactly_n_verified_unique_uploads_pass(self):
        rows, p, objs = good()
        self.assertEqual(ev.check_final(rows, p, objs, objs, expected_count=3, batch_id="batch_x"), [])

    def test_duplicate_source_rows_fail(self):
        rows, p, objs = good()
        rows.append(row(0, id="u9", client_upload_id="bg_" + "9" * 40))
        errs = ev.check_final(rows, p, objs, objs, expected_count=3, batch_id="batch_x")
        self.assertTrue(any("expected exactly 3" in e for e in errs))

    def test_duplicate_storage_key_fails(self):
        rows, p, objs = good()
        rows[1]["storage_key"] = rows[0]["storage_key"]
        self.assertTrue(any("distinct storage_key" in e for e in ev.check_final(rows, p, objs, objs, expected_count=3, batch_id="batch_x")))

    def test_unverified_or_unconfirmed_cleanup_fails(self):
        rows, p, objs = good()
        rows[0]["status"] = "uploading"; rows[1]["local_cleanup_status"] = "pending"
        errs = ev.check_final(rows, p, objs, objs, expected_count=3, batch_id="batch_x")
        self.assertTrue(any("status" in e for e in errs)); self.assertTrue(any("local_cleanup_status" in e for e in errs))

    def test_missing_or_duplicate_part_rows_fail(self):
        rows, p, objs = good()
        p["u0"] = parts(0, (1, 2))
        p["u1"] = parts(1, (1, 2, 3)) + [{"source_upload_id": "u1", "part_number": 3}]
        errs = ev.check_final(rows, p, objs, objs, expected_count=3, batch_id="batch_x")
        self.assertTrue(any("u0" in e for e in errs)); self.assertTrue(any("u1" in e for e in errs))

    def test_extra_or_missing_r2_objects_fail(self):
        rows, p, objs = good()
        listing = dict(objs); listing["raw/batch_x/dup.mp4"] = 5
        self.assertTrue(any("R2 prefix" in e for e in ev.check_final(rows, p, objs, listing, expected_count=3, batch_id="batch_x")))
        bad = dict(objs); bad[rows[0]["storage_key"]] = 1
        self.assertTrue(any("size" in e for e in ev.check_final(rows, p, bad, objs, expected_count=3, batch_id="batch_x")))
        gone = dict(objs); del gone[rows[2]["storage_key"]]
        self.assertTrue(any("missing" in e for e in ev.check_final(rows, p, gone, objs, expected_count=3, batch_id="batch_x")))

    def test_size_mismatch_between_declared_and_verified_fails(self):
        rows, p, objs = good()
        rows[0]["verified_size_bytes"] = 1
        self.assertTrue(any("verified_size_bytes" in e for e in ev.check_final(rows, p, objs, objs, expected_count=3, batch_id="batch_x")))

    def test_leaked_incomplete_multipart_upload_fails(self):
        rows, p, objs = good()
        errs = ev.check_final(rows, p, objs, objs, expected_count=3, batch_id="batch_x", open_multipart_keys=[rows[0]["storage_key"]])
        self.assertTrue(any("incomplete R2 multipart" in e for e in errs))


class Gates(unittest.TestCase):
    def test_incomplete_gate_requires_rejection_and_no_run(self):
        self.assertEqual(ev.check_gate_rejected(409, {"error": "upload batch is not ready"}), [])
        self.assertTrue(ev.check_gate_rejected(200, {"pipeline_run_id": "r"}))
        self.assertTrue(ev.check_gate_rejected(409, {"pipeline_run_id": "r"}))
        self.assertTrue(ev.check_gate_rejected(401, {"error": "Unauthorized"}))  # auth failure is not gate evidence

    def test_ready_gate_requires_full_verified_batch(self):
        ok = {"state": "ready", "expected_file_count": 3, "actual_file_count": 3, "verified_file_count": 3, "cleanup_pending_count": 0, "input_manifest": [1, 2, 3]}
        self.assertEqual(ev.check_gate_ready(ok, expected_count=3), [])
        for key, value in (("state", "uploading"), ("verified_file_count", 2), ("cleanup_pending_count", 1), ("expected_file_count", 4)):
            self.assertTrue(ev.check_gate_ready({**ok, key: value}, expected_count=3), key)
        self.assertTrue(ev.check_gate_ready({**ok, "input_manifest": [1]}, expected_count=3))


class Purge(unittest.TestCase):
    def test_only_qualification_fixture_batches_may_be_purged(self):
        ok = [row(0, source_filename="bgq_x_1.mp4"), row(1, source_filename="bgq_x_2.mp4")]
        self.assertEqual(ev.purge_guard(ok, "batch_x"), [])
        self.assertTrue(ev.purge_guard([row(0, source_filename="real-athlete-clip.mp4")], "batch_x"))
        self.assertTrue(ev.purge_guard([row(0, source_filename="bgq_x_1.mp4", batch_id="other")], "batch_x"))


class Summary(unittest.TestCase):
    def _s(self, name, ok=True, **kw):
        base = {"scenario": name, "result": "PASS" if ok else "FAIL", "failed_phase": None if ok else "completion", "failure_class": None if ok else "product",
                "failure_reason": None if ok else "x", "final_backend": {"source_uploads_rows": 3, "distinct_storage_keys": 3, "r2_objects_under_batch_prefix": 3, "open_multipart_uploads": 0},
                "final_backend_result": "PASS", "gate_incomplete": 409, "gate_ready_result": "PASS", "part_log": {"result": "PASS", "reconciles": 4, "resent_acknowledged": []}, "notes": {}}
        base.update(kw)
        return base

    def test_green_only_when_every_required_scenario_passed(self):
        names = ev.REQUIRED_SCENARIOS
        green = ev.build_summary([self._s(n) for n in names], sha="abc", run_url="u")
        self.assertTrue(green["qualified"])
        self.assertEqual(green["scenario_count"], len(names))
        self.assertIn("| process-death-resume | PASS |", green["markdown"])

    def test_missing_or_failed_scenario_blocks_qualification(self):
        names = list(ev.REQUIRED_SCENARIOS)
        missing = ev.build_summary([self._s(n) for n in names[:-1]], sha="abc", run_url="u")
        self.assertFalse(missing["qualified"]); self.assertIn(names[-1], missing["missing_scenarios"])
        failed = ev.build_summary([self._s(n, ok=(n != names[0])) for n in names], sha="abc", run_url="u")
        self.assertFalse(failed["qualified"]); self.assertIn("product", failed["markdown"])

    def test_duplicate_or_resent_evidence_blocks_even_if_scenario_says_pass(self):
        names = ev.REQUIRED_SCENARIOS
        bad = [self._s(n) for n in names]
        bad[1]["final_backend"]["source_uploads_rows"] = 4
        bad[2]["part_log"]["resent_acknowledged"] = [["a", 1]]
        bad[3]["gate_incomplete"] = 200
        result = ev.build_summary(bad, sha="abc", run_url="u")
        self.assertFalse(result["qualified"])
        self.assertGreaterEqual(len(result["integrity_failures"]), 3)


class Durable(unittest.TestCase):
    PREFS = '''<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map><string name="bg_a">{&quot;localId&quot;:&quot;bg_a&quot;,&quot;batchId&quot;:&quot;batch_x&quot;,&quot;status&quot;:&quot;UPLOADING&quot;,&quot;expectedPartCount&quot;:3,&quot;completedParts&quot;:[{&quot;partNumber&quot;:1,&quot;etag&quot;:&quot;e&quot;,&quot;sizeBytes&quot;:5}]}</string>
<string name="bg_b">{&quot;localId&quot;:&quot;bg_b&quot;,&quot;batchId&quot;:&quot;batch_x&quot;,&quot;status&quot;:&quot;VERIFIED&quot;,&quot;expectedPartCount&quot;:3,&quot;completedParts&quot;:[]}</string></map>'''

    def test_parses_durable_prefs_xml(self):
        jobs = ev.parse_prefs_xml(self.PREFS)
        self.assertEqual({j["localId"]: j["status"] for j in jobs}, {"bg_a": "UPLOADING", "bg_b": "VERIFIED"})
        self.assertEqual(ev.durable_progress(jobs), {"verified": 1, "total": 2, "acked_parts": 1})


class Notification(unittest.TestCase):
    def test_extracts_title_and_progress(self):
        dump = "NotificationRecord(0x1 pkg=com.sportreel.app id=4101)\n  extras={\n  android.title=String (SportReel — Uploading 1/3 videos)\n  android.progress=int (33)\n  android.progressMax=int (100)\n}"
        self.assertEqual(ev.parse_upload_notification(dump), {"title": "SportReel — Uploading 1/3 videos", "verified": 1, "total": 3, "progress": 33})

    def test_absent_notification_is_none(self):
        self.assertIsNone(ev.parse_upload_notification("nothing here"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
