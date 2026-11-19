import json, sys
sys.path.insert(0, __import__('os').path.dirname(__file__))
import replay_windows as R
from pipeline.action_onset import _box, _f, _track
from collections import defaultdict
want = sys.argv[2].split(',')
gt = {r[0]: r for r in json.load(open(R.S / 'gtv1_compact.json'))['rows']}
for c in R.load():
    if c['i'] not in want: continue
    tid = str(c['ev']['target_track_id'])
    by = defaultdict(list)
    for d in c['dets']:
        if _f(d, 'class_name') in (None, 'person') and _box(d) is not None and _track(d) is not None:
            by[str(_track(d))].append(d)
    a = sorted(by[tid], key=lambda d: float(_f(d, 'time_sec')))
    last = a[-1]; lt = float(_f(last, 'time_sec')); b = _box(last); cx, cy, h = (b[0]+b[2])/2, (b[1]+b[3])/2, b[3]-b[1]
    print(c['i'], 'track', tid, 'first %.2f last %.2f' % (float(_f(a[0], 'time_sec')), lt), 'box h %.0f' % h, 'llm end', c['ev']['end'], 'GT', [(round(s[1]/59.94,2), round(s[2]/59.94,2), s[3]) for s in gt[c['sha']][4]])
    for t2, ds in by.items():
        if t2 == tid: continue
        ds.sort(key=lambda d: float(_f(d, 'time_sec')))
        f = ds[0]; ft = float(_f(f, 'time_sec'))
        if lt - 0.2 <= ft <= lt + 2.0:
            fb = _box(f); dist = (((fb[0]+fb[2])/2 - cx) ** 2 + ((fb[1]+fb[3])/2 - cy) ** 2) ** 0.5
            print('    candidate continuation track', t2, 'starts %.2f ends %.2f' % (ft, float(_f(ds[-1], 'time_sec'))), 'dist %.1f box heights' % (dist / h), 'n', len(ds))
