#!/usr/bin/env python3
"""Isolated production qa_check_reel contract: provider PASS/FAIL/errors and technical gate."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

source = Path("pipeline/stages/analyzer.py").read_text()
module = ast.parse(source)
node = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "qa_check_reel")
node.decorator_list = []

class Logger:
    def warning(self, *args): pass
    def debug(self, *args): pass

class FakeModel:
    def __init__(self, text): self.text = text
    def generate_content(self, *args, **kwargs): return SimpleNamespace(text=self.text)

cases = [
    ("good", True, {"engagement_score": 90, "defects": [], "content": {}, "overall": "ok"}, "PASS"),
    ("low_score", True, {"engagement_score": 10, "defects": [], "content": {}}, "FAIL"),
    ("critical", True, {"engagement_score": 90, "defects": [{"severity": "critical"}]}, "FAIL"),
    ("technical", False, {"engagement_score": 90, "defects": []}, "FAIL"),
    ("bad_json", True, "not-json", "FAIL"),
    ("outage", True, None, "FAIL"),
]
results = {}
for label, technical_ok, response, expected in cases:
    saved, deleted = [], []
    def upload(path):
        if label == "outage": raise RuntimeError("simulated provider unavailable")
        return SimpleNamespace(name="synthetic")
    model = FakeModel(json.dumps(response) if isinstance(response, dict) else response)
    env = {
        "_check_technical_compliance": lambda path: ({"duration": 15, "aspect": 9/16}, technical_ok, [] if technical_ok else ["no audio"]),
        "_QA_PASS_CONTENT": {"hook": 10},
        "_upload_video": upload,
        "_delete_video": lambda vf: deleted.append(vf.name),
        "_QA_REEL_PROMPT": "independent review",
        "_QA_REEL_MODEL": "gemini-2.5-flash",
        "_with_retry": lambda fn: fn(),
        "_persist_qa_result": lambda result, path, sport: saved.append(result),
        "genai": SimpleNamespace(GenerativeModel=lambda model_name: model),
        "logger": Logger(),
        "Path": Path,
        "config": SimpleNamespace(QA_ENGAGEMENT_THRESHOLD=70),
        "json": json,
        "re": __import__("re"),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), "qa_contract", "exec"), env)
    verdict = env["qa_check_reel"]("/tmp/isolated.mp4", "surf")["verdict"]
    assert verdict == expected, (label, verdict, expected)
    assert len(saved) == 1, (label, "missing QA audit record")
    if label != "outage": assert deleted == ["synthetic"], (label, deleted)
    results[label] = verdict
print(json.dumps(results, sort_keys=True))
