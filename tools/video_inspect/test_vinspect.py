"""Synthetic qualification of vinspect (needs ffmpeg, av, cv2). Not a SportReel-media test."""
import subprocess, sys, tempfile, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import vinspect

def test_black_window_and_exact_time():
    d = tempfile.mkdtemp(); p = f"{d}/s.mp4"
    subprocess.check_call(["ffmpeg","-v","error","-y","-f","lavfi","-i","testsrc2=size=320x180:rate=25:duration=6",
        "-vf","drawbox=enable='between(t,2,2.2)':x=0:y=0:w=320:h=180:color=black:t=fill",
        "-pix_fmt","yuv420p","-g","25",p])
    info = vinspect.probe(p); assert abs(info["fps"]-25) < 1e-6 and abs(info["duration"]-6) < 0.05
    h = vinspect.health(p); assert h["frames"] == 150 and 2.0 <= min(h["black_frames"]) <= 2.04 and h["n_black"] in (5, 6)
    m = vinspect.frames(p, [1.0, 3.0], d + "/o"); assert all(abs(x["decoded_t"]-x["requested"]) < 0.04 for x in m)
