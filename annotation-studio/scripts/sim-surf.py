#!/usr/bin/env python3
"""Synthetic drone surf clip with an analytic ground-truth track, for testing the BOX tracker.

Not real footage, but it reproduces the things that broke tracking on the live DJI video:
  - textured, moving water (swell + ripples + sensor noise) and a breaking-wave foam band,
  - drone drift (the whole scene pans and slowly zooms),
  - a small surfer (board + body) that turns, grows/shrinks and gets partly hidden by spray,
  - two look-alike surfers (same colours) paddling nearby, one passing close to the target.
Writes <out>.mp4 (H.264, yuv420p) and <out>.json with the target's true box per frame (normalised).

usage: sim-surf.py OUT [--w 1920 --h 1080 --fps 59.94 --seconds 4]
"""
import argparse, json, math, subprocess, sys
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument('out'); ap.add_argument('--w', type=int, default=1920); ap.add_argument('--h', type=int, default=1080)
ap.add_argument('--fps', type=float, default=60000 / 1001); ap.add_argument('--seconds', type=float, default=4.0)
ap.add_argument('--seed', type=int, default=7)
a = ap.parse_args()
W, H, N = a.w, a.h, int(round(a.fps * a.seconds))
rng = np.random.default_rng(a.seed)
S = W / 1920.0                                   # all sizes are designed at 1920 wide

yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
noise_bank = [rng.normal(0, 7, (H, W)).astype(np.float32) for _ in range(8)]
ripple_phase = rng.uniform(0, 2 * math.pi, 6)
ripple_dir = rng.uniform(0, 2 * math.pi, 6)
ripple_k = rng.uniform(0.02, 0.06, 6) / S

def water(t, pan_x, pan_y, zoom):
    X = (xx - W / 2) / zoom + W / 2 + pan_x
    Y = (yy - H / 2) / zoom + H / 2 + pan_y
    h = np.zeros((H, W), np.float32)
    for i in range(6):
        h += np.sin(ripple_k[i] * (X * math.cos(ripple_dir[i]) + Y * math.sin(ripple_dir[i])) + ripple_phase[i] + t * (1.5 + i)) / 6
    swell = np.sin(X * 0.004 / S + Y * 0.006 / S - t * 1.2)
    img = np.empty((H, W, 3), np.float32)
    img[..., 0] = 20 + 18 * h + 10 * swell
    img[..., 1] = 110 + 30 * h + 18 * swell
    img[..., 2] = 150 + 35 * h + 20 * swell
    # breaking-wave foam band moving across the frame
    band = np.exp(-((Y * 0.8 - X * 0.35 - (300 * S - 140 * S * t)) / (40 * S)) ** 2)
    foam = band * (0.6 + 0.4 * np.sin(X * 0.09 / S + t * 7) * np.sin(Y * 0.07 / S - t * 5))
    img += foam[..., None] * np.array([200, 140, 100], np.float32)
    return img, X, Y

def draw_surfer(img, cx, cy, ang, sc, board_rgb, body_rgb, shorts_rgb, zoom, pan_x, pan_y):
    # surfer defined in scene coordinates -> screen
    sx = (cx - pan_x - W / 2) * zoom + W / 2
    sy = (cy - pan_y - H / 2) * zoom + H / 2
    s = sc * zoom * S
    ca, sa = math.cos(ang), math.sin(ang)
    x0, x1 = int(max(0, sx - 80 * s)), int(min(W, sx + 80 * s))
    y0, y1 = int(max(0, sy - 80 * s)), int(min(H, sy + 80 * s))
    if x1 <= x0 or y1 <= y0: return None
    lx = xx[y0:y1, x0:x1] - sx; ly = yy[y0:y1, x0:x1] - sy
    u = (lx * ca + ly * sa) / s; v = (-lx * sa + ly * ca) / s           # board axis u (length), v (width)
    reg = img[y0:y1, x0:x1]
    board = (u / 46) ** 2 + (v / 9) ** 2 <= 1
    reg[board] = board_rgb
    body = ((u + 6) / 22) ** 2 + ((v - 1) / 6) ** 2 <= 1
    reg[body] = body_rgb
    shorts = ((u - 2) / 7) ** 2 + ((v - 1) / 6.5) ** 2 <= 1
    reg[shorts] = shorts_rgb
    head = ((u + 26) / 5) ** 2 + ((v - 1) / 5) ** 2 <= 1
    reg[head] = (40, 30, 25)
    m = board | body | head
    ys, xs = np.nonzero(m)
    if not len(xs): return None
    return (x0 + xs.min(), y0 + ys.min(), x0 + xs.max() + 1, y0 + ys.max() + 1)

proc = subprocess.Popen(['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', f'{a.fps}',
                         '-i', '-', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-g', '60', '-pix_fmt', 'yuv420p',
                         a.out + '.mp4'], stdin=subprocess.PIPE)
truth = []
for n in range(N):
    t = n / a.fps
    pan_x, pan_y, zoom = 120 * S * t + 25 * S * math.sin(t * 2.1), 40 * S * math.sin(t * 1.3), 1 + 0.06 * t
    img, _, _ = water(t, pan_x, pan_y, zoom)
    img += noise_bank[n % len(noise_bank)][..., None]
    # look-alike surfers (same colours as the target), one crosses close to it mid-clip
    draw_surfer(img, 700 * S + 60 * S * t, 650 * S - 20 * S * t, 0.4, 1.0, (40, 200, 230), (225, 180, 150), (30, 30, 35), zoom, pan_x, pan_y)
    draw_surfer(img, 1500 * S - 160 * S * t, 380 * S + 25 * S * t, 2.6, 1.05, (235, 90, 120), (225, 180, 150), (30, 30, 35), zoom, pan_x, pan_y)
    # the target: rides diagonally, turns, grows, gets partly hidden by spray around t=2s
    cx, cy = 900 * S + 230 * S * t, 520 * S + 70 * S * t + 30 * S * math.sin(t * 2)
    ang, sc = -0.3 + 0.35 * t, 1.0 + 0.15 * t
    bb = draw_surfer(img, cx, cy, ang, sc, (40, 200, 230), (225, 180, 150), (30, 30, 35), zoom, pan_x, pan_y)
    if 1.8 < t < 2.3:                             # spray hides part of the surfer
        sx = (cx - pan_x - W / 2) * zoom + W / 2; sy = (cy - pan_y - H / 2) * zoom + H / 2
        r = 30 * S * zoom
        m = (xx - sx - 20 * S) ** 2 + (yy - sy) ** 2 < r * r
        img[m] = img[m] * 0.3 + np.array([235, 240, 240]) * 0.7
    truth.append(None if bb is None else {'frame': n, 'x': bb[0] / W, 'y': bb[1] / H, 'w': (bb[2] - bb[0]) / W, 'h': (bb[3] - bb[1]) / H})
    proc.stdin.write(np.clip(img, 0, 255).astype(np.uint8).tobytes())
proc.stdin.close(); proc.wait()
json.dump({'w': W, 'h': H, 'fps': a.fps, 'frames': N, 'truth': truth}, open(a.out + '.json', 'w'))
print(f'{a.out}.mp4: {N} frames {W}x{H}', file=sys.stderr)
