#!/usr/bin/env python3
"""Comprehensive test matrix for P0-01: Invocation Scope Lifecycle & Concurrency."""
from __future__ import annotations

import os
import random
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pipeline.publishable_pending_scope as scope
import pipeline.publishable_qa_evidence as qa_evidence
import pipeline.publishable_reel_policy as policy


class TestP001ScopeConcurrency(unittest.TestCase):
    def setUp(self):
        with scope._PENDING_LOCK:
            scope._PENDING_TOKENS.clear()
            scope._SCOPES_BY_INVOCATION_ID.clear()
            scope._INVOCATION_BY_TOKEN.clear()
        scope._ACTIVE_TOKEN.set(None)
        scope._ACTIVE_IDENTITY.set(None)

    def tearDown(self):
        with scope._PENDING_LOCK:
            scope._PENDING_TOKENS.clear()
            scope._SCOPES_BY_INVOCATION_ID.clear()
            scope._INVOCATION_BY_TOKEN.clear()
        scope._ACTIVE_TOKEN.set(None)
        scope._ACTIVE_IDENTITY.set(None)

    def test_single_athlete_single_thread(self):
        inv_id = "inv_single_001"
        token = scope.create_pending_scope("surfing", "athlete 1", invocation_id=inv_id)
        self.assertTrue(token.startswith("publishable_"))
        act = scope.activate_next_scope("surfing", "athlete 1", invocation_id=inv_id)
        self.assertEqual(act, token)
        self.assertEqual(scope.current_scope_token(required=True), token)
        scope.release_scope(token)
        self.assertIsNone(scope.current_scope_token())

    def test_ten_athletes_concurrent_different_completion_orders(self):
        for run_idx in range(10):
            inv_map = {f"inv_ath_{i}": f"athlete description {i}" for i in range(10)}
            tokens = {}
            for inv_id, label in inv_map.items():
                tok = scope.create_pending_scope("surfing", label, invocation_id=inv_id)
                tokens[inv_id] = tok

            shuffled_invs = list(inv_map.keys())
            random.shuffle(shuffled_invs)

            def _qa_worker(inv_id):
                label = inv_map[inv_id]
                expected_tok = tokens[inv_id]
                time.sleep(random.uniform(0.001, 0.01))
                activated = scope.activate_next_scope("surfing", label, invocation_id=inv_id)
                if activated != expected_tok:
                    return False, f"Mismatch for {inv_id}: expected {expected_tok}, got {activated}"
                time.sleep(random.uniform(0.001, 0.005))
                scope.release_scope(activated)
                return True, "ok"

            with ThreadPoolExecutor(max_workers=5) as pool:
                futures = [pool.submit(_qa_worker, inv_id) for inv_id in shuffled_invs]
                for fut in as_completed(futures):
                    ok, msg = fut.result()
                    self.assertTrue(ok, msg)

    def test_two_athletes_identical_description_no_collision(self):
        label = "surfer in black wetsuit"
        inv1 = "inv_dup_1"
        inv2 = "inv_dup_2"
        tok1 = scope.create_pending_scope("surfing", label, invocation_id=inv1)
        tok2 = scope.create_pending_scope("surfing", label, invocation_id=inv2)
        self.assertNotEqual(tok1, tok2)

        # Invocation 2 finishes QA first!
        act2 = scope.activate_next_scope("surfing", label, invocation_id=inv2)
        self.assertEqual(act2, tok2)
        scope.release_scope(act2)

        # Invocation 1 finishes QA second
        act1 = scope.activate_next_scope("surfing", label, invocation_id=inv1)
        self.assertEqual(act1, tok1)
        scope.release_scope(act1)

    def test_render_failure_before_qa_clean_discard(self):
        inv_id = "inv_failed_render"
        tok = scope.create_pending_scope("surfing", "unlucky athlete", invocation_id=inv_id)
        self.assertIn(inv_id, scope._SCOPES_BY_INVOCATION_ID)
        scope.discard_pending_scope(invocation_id=inv_id, token=tok)
        self.assertNotIn(inv_id, scope._SCOPES_BY_INVOCATION_ID)
        with self.assertRaises(RuntimeError):
            scope.activate_next_scope("surfing", "unlucky athlete", invocation_id=inv_id)

    def test_qa_failure_mid_execution_no_state_leak(self):
        inv_id = "inv_qa_fail"
        tok = scope.create_pending_scope("surfing", "failing qa athlete", invocation_id=inv_id)
        act = scope.activate_next_scope("surfing", "failing qa athlete", invocation_id=inv_id)
        self.assertEqual(act, tok)
        try:
            raise ValueError("simulated network crash in Gemini QA")
        except ValueError:
            pass
        finally:
            scope.release_scope(act)
        self.assertIsNone(scope.current_scope_token())

    def test_retry_reuses_active_invocation(self):
        inv_id = "inv_retry"
        tok = scope.create_pending_scope("surfing", "reedit athlete", invocation_id=inv_id)
        act = scope.activate_next_scope("surfing", "reedit athlete", invocation_id=inv_id)
        self.assertEqual(act, tok)
        # During re-edit, pending_key is called while scope is active:
        reedit_key = scope.pending_key("surfing", "reedit athlete", invocation_id=inv_id)
        self.assertEqual(reedit_key, tok, "Re-edit must reuse active scope token, not create a new one")
        scope.release_scope(act)

    def test_cannot_consume_scope_twice(self):
        inv_id = "inv_double_consume"
        tok = scope.create_pending_scope("surfing", "athlete", invocation_id=inv_id)
        act = scope.activate_next_scope("surfing", "athlete", invocation_id=inv_id)
        self.assertEqual(act, tok)
        scope.release_scope(act)
        with self.assertRaises(RuntimeError):
            scope.activate_next_scope("surfing", "athlete", invocation_id=inv_id)

    def test_unknown_explicit_id_never_consumes_same_label_fifo(self):
        token = scope.create_pending_scope("surfing", "identical label", invocation_id="valid-1")
        with self.assertRaises(RuntimeError):
            scope.activate_next_scope("surfing", "identical label", invocation_id="unknown-2")
        self.assertEqual(scope.activate_next_scope("surfing", "identical label", invocation_id="valid-1"), token)
        scope.release_scope(token)

    def test_duplicate_id_cannot_override_another_pending_render(self):
        first = scope.create_pending_scope("surfing", "person-a", invocation_id="dup-id")
        with self.assertRaises((ValueError, RuntimeError)):
            scope.create_pending_scope("surfing", "person-b", invocation_id="dup-id")
        self.assertEqual(scope.activate_next_scope("surfing", "person-a", invocation_id="dup-id"), first)
        scope.release_scope(first)

    def test_render_stamp_keeps_one_explicit_identity_not_aliases(self):
        token = scope.create_pending_scope("surfing", "person-a", invocation_id="run-scope-1")
        evs = [("draft.mp4", [{"type": "ride", "start": 1.0, "end": 5.0}])]
        stamped = policy._stamp_render_invocation(evs, token, invocation_id="run-scope-1")
        self.assertEqual(stamped[0][1][0]["_render_invocation_id"], "run-scope-1")
        self.assertEqual(scope._SCOPES_BY_INVOCATION_ID, {"run-scope-1": token})
        scope.release_scope(scope.activate_next_scope("surfing", "person-a", invocation_id="run-scope-1"))
        self.assertFalse(scope._SCOPES_BY_INVOCATION_ID)
        self.assertFalse(scope._INVOCATION_BY_TOKEN)

    def test_100_concurrent_simulations_zero_leaks_or_collisions(self):
        """GATE-03 requirement: 100 concurrent simulation runs without scope collision."""
        success_count = 0
        for iteration in range(100):
            sport = "surfing"
            # Mix unique and duplicated labels
            labels = [
                "surfer in green t-shirt",
                "surfer in black wetsuit",
                "surfer in black wetsuit",  # duplicate description
                "woman in dark bikini",
                "surfer in red rash guard",
            ]
            inv_ids = [f"iter_{iteration}_ath_{idx}" for idx in range(len(labels))]
            created = {}
            for inv_id, label in zip(inv_ids, labels):
                tok = scope.create_pending_scope(sport, label, invocation_id=inv_id)
                created[inv_id] = (label, tok)

            results = {}
            # Random worker execution order
            def worker(inv_id):
                lbl, expected = created[inv_id]
                time.sleep(random.uniform(0.0001, 0.002))
                act = scope.activate_next_scope(sport, lbl, invocation_id=inv_id)
                time.sleep(random.uniform(0.0001, 0.001))
                scope.release_scope(act)
                return inv_id, act == expected

            with ThreadPoolExecutor(max_workers=8) as pool:
                futs = [pool.submit(worker, inv) for inv in inv_ids]
                for fut in as_completed(futs):
                    inv_id, match = fut.result()
                    results[inv_id] = match

            self.assertTrue(all(results.values()), f"Collision in iteration {iteration}")
            success_count += 1

        self.assertEqual(success_count, 100)
        self.assertEqual(len(scope._SCOPES_BY_INVOCATION_ID), 0, "No leaked scopes in _SCOPES_BY_INVOCATION_ID")
        self.assertEqual(len(scope._PENDING_TOKENS), 0, "No leaked scopes in _PENDING_TOKENS")
        self.assertEqual(len(scope._INVOCATION_BY_TOKEN), 0, "No reverse map leaks")



    def test_conflicting_explicit_discard_cannot_delete_another_scope(self):
        first = scope.create_pending_scope("surfing", "one", invocation_id="run-one")
        second = scope.create_pending_scope("surfing", "two", invocation_id="run-two")
        with self.assertRaises(RuntimeError):
            scope.discard_pending_scope(invocation_id="run-one", token=second)
        self.assertEqual(scope.activate_next_scope("surfing", "one", invocation_id="run-one"), first)
        scope.release_scope(first)
        self.assertEqual(scope.activate_next_scope("surfing", "two", invocation_id="run-two"), second)
        scope.release_scope(second)

    def test_active_scope_rejects_foreign_explicit_invocation(self):
        first = scope.create_pending_scope("surfing", "one", invocation_id="active-one")
        second = scope.create_pending_scope("surfing", "two", invocation_id="active-two")
        self.assertEqual(scope.activate_next_scope("surfing", "one", invocation_id="active-one"), first)
        try:
            with self.assertRaises(RuntimeError):
                scope.pending_key("surfing", "two", invocation_id="active-two")
        finally:
            scope.release_scope(first)
        self.assertEqual(scope.activate_next_scope("surfing", "two", invocation_id="active-two"), second)
        scope.release_scope(second)


if __name__ == "__main__":
    unittest.main()
