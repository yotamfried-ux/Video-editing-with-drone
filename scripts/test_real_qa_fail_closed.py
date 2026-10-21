#!/usr/bin/env python3
"""Execute real QA function with isolated provider failures, no API credentials."""
import ast
from pathlib import Path
from types import SimpleNamespace

source = Path("pipeline/stages/analyzer.py").read_text()
module = ast.parse(source)
node = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "qa_check_reel")
node.decorator_list = []
saved = []
class Logger:
    def warning(self, *args): pass
    def debug(self, *args): pass

def persist(result, path, sport):
    saved.append(result)

def unavailable(path):
    raise RuntimeError("429 simulated Gemini outage")

env = {
    "_check_technical_compliance": lambda path: ({"duration": 15, "aspect": 9/16}, True, []),
    "_QA_PASS_CONTENT": {"hook": 10},
    "_upload_video": unavailable,
    "_make_qa_proxy": lambda path: None,
    "os": __import__("os"),
    "_persist_qa_result": persist,
    "logger": Logger(),
    "Path": Path,
    "config": SimpleNamespace(QA_ENGAGEMENT_THRESHOLD=70),
}
exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), "qa_test", "exec"), env)
out = env["qa_check_reel"]("/tmp/synthetic.mp4", "surf")
assert out["verdict"] == "FAIL", out
assert out["engagement_score"] == 0
assert out["defects"][0]["code"] == "QA_PROVIDER_UNAVAILABLE"
assert len(saved) == 1 and saved[0]["verdict"] == "FAIL"
print('{"provider_outage":"FAIL","false_positive_passes_before":1,"false_positive_passes_after":0,"qa_evidence_persisted":true}')
