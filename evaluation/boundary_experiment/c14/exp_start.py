"""EXP-14-001 (development plane, free): action already in progress at the recording start.
Paired replay over every frozen run: same analyzer events, same sidecars, same evaluator; baseline = current
production window code, candidate = baseline + C1 (camera-compensated motion from the recording start)."""
import json, sys, statistics, glob
sys.argv = sys.argv[:1] + ['/dev/null']
sys.path.insert(0, __import__('os').path.dirname(__file__))
import replay_windows as R
from pathlib import Path
from collections import defaultdict
from pipeline.action_onset import stitched_actor_detections, _box, _f, _track
S = R.S
gt = {r[0]: r for r in json.load(open(S / 'gtv1_compact.json'))['rows']}
T = float(__import__('os').environ.get('C1_T', '1.0'))

def centre(d):
    b = _box(d); return ((b[0]+b[2])/2, (b[1]+b[3])/2, b[3]-b[1])

def at(td, t, tol=0.25):
    c = [d for d in td if abs(float(_f(d, 'time_sec')) - t) <= tol]
    return min(c, key=lambda d: abs(float(_f(d, 'time_sec')) - t)) if c else None

def rel_motion(dets, actor, t0, t1):
    a0, a1 = at(actor, t0), at(actor, t1)
    if not a0 or not a1: return None
    (x0, y0, h0), (x1, y1, h1) = centre(a0), centre(a1)
    ids = {str(_track(d)) for d in actor}; by = defaultdict(list)
    for d in dets:
        if str(_track(d)) in ids or _f(d, 'class_name') not in (None, 'person') or _box(d) is None: continue
        by[str(_track(d))].append(d)
    sh = []
    for td in by.values():
        b0, b1 = at(td, t0), at(td, t1)
        if b0 and b1:
            (p0, q0, _), (p1, q1, _) = centre(b0), centre(b1); sh.append((p1 - p0, q1 - q0))
    if len(sh) < 2: return None
    mx = statistics.median(s[0] for s in sh); my = statistics.median(s[1] for s in sh)
    return (((x1 - x0) - mx) ** 2 + ((y1 - y0) - my) ** 2) ** 0.5 / ((h0 + h1) / 2) / (t1 - t0)

def c1(e, ev, dets):
    start = float(e['start'])
    if start <= 0.05: return e
    actor = stitched_actor_detections(dets, ev['target_track_id'])
    if not actor or float(_f(actor[0], 'time_sec')) > 0.5: return e
    t = 0.0
    while t < start - 1e-6:
        m = rel_motion(dets, actor, t, min(t + 1.0, max(start, t + 0.5)))
        if m is None or m < T: return e
        t += 0.5
    return {**e, 'start': 0.0, 'c1_in_progress_from_recording_start': start}

def rides(sha):
    segs = sorted([s for s in gt[sha][4] if s[3] == 'include'], key=lambda s: s[1]); out = []
    for s in segs:
        if out and out[-1][2] == s[4] and s[1] - out[-1][1] <= 3: out[-1][1] = max(out[-1][1], s[2])
        else: out.append([s[1], s[2], s[4]])
    return [(a / 59.94, b / 59.94) for a, b, _ in out]

def err(sha, s, e):
    rs = rides(sha)
    if not rs: return None
    best = max(rs, key=lambda r: min(r[1], e) - max(r[0], s))
    if min(best[1], e) - max(best[0], s) <= 0: return None
    return s - best[0], e - best[1]

def main():
    tot = defaultdict(lambda: [0, 0, 0, 0, 0.0, 0.0]); changes = []
    runs = sorted(glob.glob(str(S / 'r4*/x')) + glob.glob(str(S / 'run43920602179/x')) + glob.glob(str(S / 'q*/x')) + [str(S / 'p196/x')])
    for run in runs:
        R.X = Path(run)
        try: evs = R.load()
        except Exception as ex: print('skip', run, ex); continue
        for c in evs:
            if c['sha'] not in gt: continue
            dur = gt[c['sha']][3][-1][1] / 59.94
            try:
                b = R.run_policy(c['ev'], c['dets'], dur)
            except Exception as ex:
                print('err', run, c['i'], ex); continue
            cand = c1(b, c['ev'], c['dets'])
            eb, ec = err(c['sha'], b['start'], b['end']), err(c['sha'], cand['start'], cand['end'])
            if eb is None: continue
            k = run.split('/')[-2]
            t = tot[k]; t[0] += 1
            t[1] += abs(eb[0]) > 0.5; t[2] += abs(ec[0]) > 0.5
            t[4] = max(t[4], abs(eb[0])); t[5] = max(t[5], abs(ec[0]))
            if cand['start'] != b['start']:
                changes.append((k, c['i'], round(b['start'], 2), round(eb[0], 2), round(ec[0], 2)))
    print('T =', T)
    for k, t in tot.items(): print('%-16s events %2d  start>0.5s: baseline %2d -> C1 %2d   max |start err| %.2f -> %.2f' % (k, t[0], t[1], t[2], t[4], t[5]))
    print('sum baseline', sum(t[1] for t in tot.values()), 'C1', sum(t[2] for t in tot.values()))
    print('changed events (run, src, baseline start, signed err before, after):')
    for ch in changes: print('  ', ch, 'WORSE' if abs(ch[4]) > abs(ch[3]) + 1e-6 else '')

if __name__ == '__main__':
    main()
