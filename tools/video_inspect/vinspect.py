#!/usr/bin/env python3
"""Real-video inspection helper (frames decoded, not metadata only).

Subcommands:
  probe   <video>                         duration/fps/frames/pts via ffprobe
  frames  <video> <t1,t2,...> <outdir>    exact-time frame extraction (PyAV seek+decode)
  sheet   <video> <start> <end> <n> <out> contact sheet with timestamp labels
  health  <video>                         decode all frames: black / frozen / repeated / pts jumps
  compare <src> <src_t> <reel> <reel_t> <out>  side-by-side frame from source vs reel
Every frame written is logged to <outdir>/frames_manifest.json (time, pts, sha256).
"""
import sys, json, subprocess, hashlib, os
import av, cv2, numpy as np

def probe(p):
    o = subprocess.check_output(["ffprobe","-v","error","-print_format","json","-show_format","-show_streams",p])
    j = json.loads(o); v = next(s for s in j["streams"] if s["codec_type"]=="video")
    n, d = map(int, v["avg_frame_rate"].split("/"))
    return {"duration": float(j["format"]["duration"]), "fps": n/d, "w": v["width"], "h": v["height"],
            "nb_frames": v.get("nb_frames"), "codec": v["codec_name"], "time_base": v["time_base"]}

def grab(p, t):
    """Decode the frame whose pts is nearest to (and not before) t."""
    c = av.open(p); s = c.streams.video[0]
    c.seek(int(max(t-2,0)/s.time_base), stream=s, backward=True)
    best = None
    for f in c.decode(s):
        ft = float(f.pts*s.time_base)
        if ft + 1e-6 >= t: best = (f.to_ndarray(format="bgr24"), ft, f.pts); break
    c.close(); return best

def frames(p, ts, out):
    os.makedirs(out, exist_ok=True); man = []
    for t in ts:
        img, ft, pts = grab(p, t)
        fn = f"{out}/f_{t:09.3f}.jpg"; cv2.imwrite(fn, img)
        man.append({"requested": t, "decoded_t": round(ft,4), "pts": pts, "file": fn,
                    "sha256": hashlib.sha256(open(fn,'rb').read()).hexdigest()})
    json.dump(man, open(f"{out}/frames_manifest.json","w"), indent=1); return man

def label(img, txt):
    cv2.putText(img, txt, (6,22), cv2.FONT_HERSHEY_SIMPLEX, .6, (0,0,0), 4); cv2.putText(img, txt, (6,22), cv2.FONT_HERSHEY_SIMPLEX, .6, (255,255,255), 1); return img

def sheet(p, a, b, n, out):
    ts = np.linspace(a, b, n); tiles = []
    for t in ts:
        img, ft, _ = grab(p, float(t)); img = cv2.resize(img, (320, int(320*img.shape[0]/img.shape[1])))
        tiles.append(label(img, f"t={ft:.2f}s"))
    cols = min(4, n); rows = (n+cols-1)//cols; h, w = tiles[0].shape[:2]
    canvas = np.zeros((rows*h, cols*w, 3), np.uint8)
    for i, tl in enumerate(tiles): canvas[(i//cols)*h:(i//cols+1)*h, (i%cols)*w:(i%cols+1)*w] = tl
    cv2.imwrite(out, canvas); return out

def health(p):
    c = av.open(p); s = c.streams.video[0]; prev = None; ptsl = []; black = []; frozen = []; dup = 0
    for i, f in enumerate(c.decode(s)):
        g = cv2.cvtColor(f.to_ndarray(format="bgr24"), cv2.COLOR_BGR2GRAY); t = float(f.pts*s.time_base); ptsl.append(t)
        if g.mean() < 8: black.append(round(t,3))
        if prev is not None:
            d = float(np.mean(cv2.absdiff(g, prev)))
            if d < 0.01: dup += 1; frozen.append(round(t,3))
        prev = g
    dts = np.diff(ptsl); exp = np.median(dts) if len(dts) else 0
    jumps = [round(ptsl[i+1],3) for i,x in enumerate(dts) if x > 2*exp or x <= 0]
    return {"frames": len(ptsl), "black_frames": black[:20], "n_black": len(black), "n_frozen": len(frozen),
            "frozen_at": frozen[:20], "pts_jumps": jumps[:20], "median_dt": float(exp)}

def compare(s, st, r, rt, out):
    a, fa, _ = grab(s, st); b, fb, _ = grab(r, rt)
    h = 360; a = cv2.resize(a, (int(a.shape[1]*h/a.shape[0]), h)); b = cv2.resize(b, (int(b.shape[1]*h/b.shape[0]), h))
    cv2.imwrite(out, np.hstack([label(a, f"SRC {fa:.2f}s"), label(b, f"REEL {fb:.2f}s")])); return out

if __name__ == "__main__":
    c = sys.argv[1]; a = sys.argv[2:]
    if c == "probe": print(json.dumps(probe(a[0]), indent=1))
    elif c == "frames": print(json.dumps(frames(a[0], [float(x) for x in a[1].split(",")], a[2]), indent=1))
    elif c == "sheet": print(sheet(a[0], float(a[1]), float(a[2]), int(a[3]), a[4]))
    elif c == "health": print(json.dumps(health(a[0]), indent=1))
    elif c == "compare": print(compare(a[0], float(a[1]), a[2], float(a[3]), a[4]))
