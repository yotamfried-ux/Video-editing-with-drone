import json, sys
sys.path.insert(0, __import__('os').path.dirname(__file__))
from replay_windows import load, S, wr
from pipeline.action_onset import stitched_actor_detections, _motion_per_sec, _box, _f
gt = {r[0]: r for r in json.load(open(S / 'gtv1_compact.json'))['rows']}
for c in load():
    tid = c['ev']['target_track_id']
    st = stitched_actor_detections(c['dets'], tid)
    segs = [s for s in gt[c['sha']][4] if s[3] == 'include']
    gts = min((s[1] for s in segs), default=None)
    gts = None if gts is None else round(gts / 59.94, 2)
    first = round(float(_f(st[0], 'time_sec')), 2) if st else None
    # motion per 0.5 s step from 0 to analyzer start
    steps = []
    t = 0.0
    while t < c['ev']['start'] + 0.01:
        w = [d for d in st if t <= float(_f(d, 'time_sec')) <= t + 1.0]
        m = _motion_per_sec(w)
        steps.append('%.1f:%s' % (t, '-' if m is None else '%.2f' % m))
        t += 0.5
    raw = [d for d in c['dets'] if str(_f(d, 'track_id')) == str(tid)]
    rawfirst = round(min(float(_f(d,'time_sec')) for d in raw), 2) if raw else None
    print(c['i'], 'trk', tid, 'GTstart', gts, 'llm', c['ev']['start'], 'setup', c['ev']['setup_start'],
          'stitched_first', first, 'raw_first', rawfirst, 'n_stitch_tracks', len({str(_f(d,"track_id")) for d in st}), ' '.join(steps[:14]))
