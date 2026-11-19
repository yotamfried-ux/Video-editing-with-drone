"""C14 boundary replay (development plane): rebuild each selected event's pre-normalisation window from a frozen run
(analyzer start/end/setup/outcome from the diagnostics, frozen perception sidecar), run the CURRENT production
window code, and print the result next to what the run actually rendered. GT is read only in score()."""
import json, re, sys, importlib
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]; sys.path.insert(0, str(ROOT))
X = Path(sys.argv[1]); S = Path(__import__('os').environ['C14_DATA'])
from pipeline.perception import runtime as rt
import pipeline.window_refinement as wr, pipeline.complete_action_window_policy as cw

def idx(name):
    m = re.search(r'_(\d{4})_D', str(name)); return m.group(1) if m else str(name)

def load():
    pred = json.load(open(X / 'predictions.v1.json'))
    audit = {c['candidate_id']: c for c in json.load(open(X / 'selection_decision_audit.json'))['candidates']}
    led = {c['candidate_id']: c for c in json.load(open(X / 'candidate_decision_ledger.json'))['candidates']}
    trace = {}
    def walk(x):
        if isinstance(x, dict):
            if 'window_refinement' in x:
                trace[(idx(x.get('source_video') or x.get('_src') or x.get('source')), round(float(x.get('end') or 0), 1))] = x
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
    walk(json.load(open(X / 'draft_decision_trace.json')))
    out = []
    for src in pred['sources']:
        i = idx(src['source_video'])
        side = next(X.glob(f'sidecars/*_{i}_D.perception.json'))
        payload = json.load(open(side))
        dets = rt._detections_from_payload(str(side), payload)
        for e in src['events']:
            if e['decision'] != 'selected': continue
            fw = led[e['candidate_id']]['final_source_window']
            t = trace.get((i, round(fw['end'], 1)), {})
            out.append(dict(i=i, sha=src['source_sha256'], cid=e['candidate_id'], dets=dets, payload=payload,
                            ev={'start': e['start_sec'], 'end': e['end_sec'], 'setup_start': t.get('setup_start'),
                                'setup_start_raw': t.get('setup_start'), 'outcome_end': t.get('outcome_end'),
                                'description': audit[e['candidate_id']].get('description'),
                                'timing_evidence': t.get('timing_evidence'), 'event_type': e['event_type'],
                                'sport': 'surfing', 'target_track_id': e['outputs'][0]['track_id']},
                            rendered=(fw['start'], fw['end'])))
    return out

def run_policy(ev, dets, duration, mod=cw):
    r = wr.refine_event_window(dict(ev), dets)
    e = mod.extend_to_setup(r); e = mod.extend_to_recording_start(e)
    e = mod.extend_to_outcome(e, duration); e = mod.extend_through_fall(e, duration); e = mod.extend_to_recording_end(e, duration)
    return e

if __name__ == '__main__':
    gt = {r[0]: r for r in json.load(open(S / 'gtv1_compact.json'))['rows']}
    for c in load():
        dur = gt[c['sha']][3][-1][1] / 59.94   # recording length (metadata) from the reviewed range
        e = run_policy(c['ev'], c['dets'], dur)
        print(c['i'], 'setup', c['ev']['setup_start'], 'llm %.2f-%.2f' % (c['ev']['start'], c['ev']['end']),
              '| replay %.2f-%.2f' % (e['start'], e['end']), '| rendered %.2f-%.2f' % c['rendered'],
              'OK' if abs(e['start'] - c['rendered'][0]) < 0.06 and abs(e['end'] - c['rendered'][1]) < 0.06 else 'DIFF')
