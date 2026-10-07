#!/usr/bin/env python3
from __future__ import annotations
import json, os, tempfile, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))

def qa_simulations():
    import pipeline.source_evidence_runner as r
    assert r._parse_qa_json('''```json
{"defects":[],"engagement_score":91,"overall":"ok"}
```''')["engagement_score"]==91
    f=tempfile.NamedTemporaryFile(delete=False,suffix=".mp4"); f.write(b"x"); f.close()
    r.make_source_clips=lambda _:[f.name]
    class Resp:
        def __init__(self,text): self.text=text
    class Model:
        calls=0
        def generate_content(self,*a,**k):
            self.calls+=1
            if self.calls==1: return Resp('{"defects": [}')
            return Resp('{"content":{},"defects":[],"engagement_score":90,"overall":"ok"}')
    model=Model()
    class G:
        def GenerativeModel(self,model_name): return model
    class A:
        _QA_REEL_PROMPT="qa"; _QA_REEL_MODEL="m"; genai=G()
        def _check_technical_compliance(self,p): return {},True,[]
        def _upload_video(self,p): return {"p":p}
        def _delete_video(self,x): pass
        def _with_retry(self,fn): return fn()
        def _persist_qa_result(self,*a): pass
    base=lambda *a,**k: {"verdict":"PASS","defects":[],"overall":"base"}
    out=r.with_source_evidence(A(),base,"reel.mp4",sport="surfing",context={"source_windows":[{"source":f.name}]})
    assert out["verdict"]=="PASS" and out["source_evidence_visual_uploaded"] is True and model.calls==2
    f2=tempfile.NamedTemporaryFile(delete=False,suffix=".mp4"); f2.write(b"x"); f2.close(); r.make_source_clips=lambda _:[f2.name]
    class BadModel:
        def generate_content(self,*a,**k): return Resp('{"defects": [}')
    class G2:
        def GenerativeModel(self,model_name): return BadModel()
    A.genai=G2()
    out=r.with_source_evidence(A(),base,"reel.mp4",sport="surfing",context={"source_windows":[{"source":f2.name}]})
    assert out["verdict"]=="FAIL" and out["source_evidence_visual_uploaded"] is True
    assert out["qa_failure_reason"]=="response_parse_failed"
    assert "QA response unavailable" in out["defects"][-1]["note"] or "QA response" in out["defects"][-1]["note"]

def reel_name_simulation():
    from pipeline.stages.editor import _multi_reel_stem
    a=_multi_reel_stem("same_source","athlete red board",0,1)
    b=_multi_reel_stem("same_source","athlete blue board",0,1)
    assert a != b, (a,b)
    assert a == _multi_reel_stem("same_source","athlete red board",0,1)

def manifest_simulations():
    import pipeline.publishable_reel_policy as p
    payload=p._empty_manifest()
    payload["athletes"]=[{"parts":[{"local_path":"/render/a/reel.mp4","upload_path_aliases":[]}]}]
    assert p._find_upload_part(payload,"/stage/b/reel.mp4") is not None
    payload["athletes"].append({"parts":[{"local_path":"/render/c/reel.mp4","upload_path_aliases":[]}]})
    assert p._find_upload_part(payload,"/stage/b/reel.mp4") is None

def coverage_simulation():
    from scripts.build_athlete_coverage_report import build_report
    with tempfile.TemporaryDirectory() as d:
        ledger=Path(d)/"ledger.json"; audit=Path(d)/"audit.json"
        ledger.write_text(json.dumps({"candidates":[
            {"athlete_id":"athlete_A","selected":True,"event_id":"e1","source":"a.mp4","start":1,"end":8},
            {"athlete_id":"athlete_A","selected":False,"event_id":"e2","source":"a.mp4","start":10,"end":18},
        ]}))
        audit.write_text(json.dumps({"selected":[{"athlete_id":"athlete_A","event_id":"e1"}]}))
        report=build_report(ledger,audit)
        assert report["summary"]["coverage_gap_cluster_count"]==0
        assert report["summary"]["athlete_accountability_rate"]==1.0

def main():
    qa_simulations(); reel_name_simulation(); manifest_simulations(); coverage_simulation()
    print("Production QA/manifest/coverage simulations passed")
    return 0
if __name__=="__main__": raise SystemExit(main())
