import json, sys, glob
sys.argv = sys.argv[:1] + ['/dev/null']
sys.path.insert(0, __import__('os').path.dirname(__file__))
import replay_windows as R, exp_start as E
from pathlib import Path
out = {}
for run in sorted(glob.glob(str(R.S / 'r4*/x')) + glob.glob(str(R.S / 'run43920602179/x')) + glob.glob(str(R.S / 'q*/x')) + [str(R.S / 'p196/x')]):
    R.X = Path(run)
    try: evs = R.load()
    except Exception: continue
    for c in evs:
        if c['sha'] not in E.gt: continue
        dur = E.gt[c['sha']][3][-1][1] / 59.94
        b = R.run_policy(c['ev'], c['dets'], dur)
        e = E.err(c['sha'], b['start'], b['end'])
        out['%s|%s|%s' % (run.split('/')[-2], c['i'], c['cid'])] = [round(b['start'], 2), round(b['end'], 2), None if e is None else [round(e[0], 2), round(e[1], 2)]]
json.dump(out, open(sys.stdin.readline().strip() if False else '/dev/stdout', 'w'), indent=0)
