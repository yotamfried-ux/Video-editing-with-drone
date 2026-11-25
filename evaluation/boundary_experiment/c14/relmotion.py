import json, sys, statistics
sys.path.insert(0, __import__('os').path.dirname(__file__))
from replay_windows import load, S
from pipeline.action_onset import stitched_actor_detections, _box, _f, _track
from collections import defaultdict
gt = {r[0]: r for r in json.load(open(S / 'gtv1_compact.json'))['rows']}

def centre(d):
    b = _box(d); return ((b[0]+b[2])/2, (b[1]+b[3])/2, b[3]-b[1])

def rel_motion(dets, actor, t0, t1):
    """actor displacement minus median displacement of the other persons seen at both ends, per sec, in actor heights"""
    def at(track_dets, t, tol=0.25):
        c = [d for d in track_dets if abs(float(_f(d,'time_sec'))-t) <= tol]
        return min(c, key=lambda d: abs(float(_f(d,'time_sec'))-t)) if c else None
    a0, a1 = at(actor, t0), at(actor, t1)
    if not a0 or not a1: return None
    (x0,y0,h0),(x1,y1,h1) = centre(a0), centre(a1)
    by = defaultdict(list)
    actor_ids = {str(_track(d)) for d in actor}
    for d in dets:
        tid = str(_track(d))
        if tid in actor_ids or _f(d,'class_name') not in (None,'person') or _box(d) is None: continue
        by[tid].append(d)
    shifts = []
    for tid, td in by.items():
        b0, b1 = at(td, t0), at(td, t1)
        if b0 and b1:
            (p0,q0,_),(p1,q1,_) = centre(b0), centre(b1); shifts.append((p1-p0, q1-q0))
    if len(shifts) < 2: return None
    mx = statistics.median(s[0] for s in shifts); my = statistics.median(s[1] for s in shifts)
    h = (h0+h1)/2
    return (((x1-x0)-mx)**2 + ((y1-y0)-my)**2) ** 0.5 / h / (t1-t0), len(shifts)

for c in load():
    tid = c['ev']['target_track_id']
    st = stitched_actor_detections(c['dets'], tid)
    segs = [s for s in gt[c['sha']][4] if s[3] == 'include']
    gts = round(min(s[1] for s in segs)/59.94,2) if segs else None
    out = []; t = 0.0
    while t < max(c['ev']['start'], 3.0) + 0.01:
        r = rel_motion(c['dets'], st, t, t+1.0)
        out.append('%.1f:%s' % (t, '-' if r is None else '%.2f(%d)' % r)); t += 0.5
    print(c['i'], 'GT', gts, 'llm', c['ev']['start'], 'setup', c['ev']['setup_start'], ' '.join(out[:12]))
