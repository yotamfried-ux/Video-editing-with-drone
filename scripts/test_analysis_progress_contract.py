#!/usr/bin/env python3
"""A mixed batch must emit per-source progress even with staggered worker times."""
from __future__ import annotations

import ast
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


class TestAnalysisProgressContract(unittest.TestCase):
    def test_completion_progress_is_monotonic_and_results_preserve_source_order(self):
        source = Path("pipeline/orchestrator.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        target = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                      and node.name == "_analyze_downloaded")
        ns = {"_ANALYSIS_WORKERS": 3, "ThreadPoolExecutor": ThreadPoolExecutor,
              "as_completed": as_completed}
        seen = []
        ns["_analysis_progress_update"] = lambda **kw: seen.append(kw)

        def fake_analyze(item):
            # The first source takes longest; completion order differs from input.
            time.sleep({"A": 0.06, "B": 0.012, "C": 0.025}[item["meta"]["name"]])
            return {"meta": item["meta"], "analysis": {"persons": []}, "path": item["path"]}

        ns["_analyze_one_source"] = fake_analyze
        exec(compile(ast.Module(body=[target], type_ignores=[]),
                     "pipeline/orchestrator.py", "exec"), ns)
        files = [{"path": key, "meta": {"name": key, "id": key}} for key in ("A", "B", "C")]
        results = ns["_analyze_downloaded"](files)
        self.assertEqual([result["meta"]["name"] for result in results], ["A", "B", "C"])
        self.assertEqual([row["completed"] for row in seen], [1, 2, 3])
        self.assertEqual(seen[-1]["total"], 3)
        self.assertEqual(seen[-1]["failed"], 0)
        self.assertEqual(len(seen), 3)
        self.assertTrue(all(row["elapsed_seconds"] >= 0 for row in seen))


if __name__ == "__main__":
    unittest.main()
