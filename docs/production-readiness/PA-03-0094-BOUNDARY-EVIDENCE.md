# PA-03 — end boundary of the 0094 ride (evidence for an owner decision; GT-v1 unchanged)

## Inputs

**Source:** `2026-10-03T12-19-53_DJI_20260720160337_0094_D.MP4`
- SHA-256 `250c3592fd87ba05dd8a56eee9d50de5cfcbeb079f261793d5201a31d7eda963`
- 59.94 fps, 36.7 s.

**GT-v1** (digest `b31fd9b4…27c9`, frozen):
- athlete 9524ac02 has **include 0.00–13.23 s** (wave_ride);
- athlete d805a9b1 (the tandem) has include 16.85–36.69 s;
- 13.23–16.85 s is reviewed but included for nobody.

**The GT annotator's box track for 9524ac02** continues to 22.77 s.
- His box centre keeps moving until about 15.0 s.
- His box height (fraction of frame height) falls from 0.37 at 13.0–13.5 s to 0.29 at 15.0 s and 0.26 from 15.5 s
  onward.
- These are aggregate figures; the boxes themselves are private and not committed.

**Rendered evidence:** the EXP-11-001 reel (run 44252428407).
- File "DRAFT_Man with long dark hair and beard_ wearing a black_20261118.mp4", SHA-256 `423a3d65…3e5231`.
- Its first clip is a tracked crop on track 37 (= 9524ac02), source 2.0–22.5 s, real-time.
- So reel time = source time − 2.0 s, within about ±0.25 s.

## Frames (2 fps, source time burnt in), viewed

| Source time | What the frames show |
|---|---|
| 11.0–12.5 s | standing, riding the green face, turning |
| 13.0–14.5 s | **still standing and riding**, now in the broken whitewater, moving with the foam |
| 15.0 s | starts to crouch |
| 15.5–17.5 s | kneeling, then prone on the board in the foam: the standing ride is over |

The contact sheet sits in the session's scratch evidence and is not committed (a person's image). It can be
regenerated from the reel artifact of run 44252428407 with:

`ffmpeg -ss 9 -t 7 -i <reel> -vf fps=2,tile=7x2`

## 13.2 s versus 16 s

| Candidate end | Supported by |
|---|---|
| 13.23 s (GT-v1) | the moment the wave face breaks; a "green-wave riding only" labelling convention |
| **about 15.2 s** | the frames: the athlete keeps a standing ride in the whitewater until he crouches (15.0 s) and goes prone (15.5 s) |
| 16 s | not supported: he is already prone at 15.5–16.0 s |

## What needs deciding

This is a labelling-policy question: does standing whitewater riding after the wave breaks belong to the action?
- **If no:** GT-v1 stays as it is.
- **If yes:** create a new GT version with 9524ac02's include ending at about 15.2 s (exact frame to be set in the
  annotation studio). Score all runs on both versions.

GT-v1 is never edited. No pipeline value was tuned to either end, and the rejected E1 end rule (cycle 12) was not
used to choose between them.
