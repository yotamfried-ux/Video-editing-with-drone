# EXP-14-002 — observed action validity v2 (pre-registered; NOT RUN — needs owner authorization)

- **Why a new experiment:** EXP-08-001 (run 44067400479) asked one judgement question ("did the target stand up?")
  on 360p / 4 fps proxies. It kept the 0155 failed take-off in 3/3 calls and rejected a GT-valid prone ride twice.
  Standing is also not required for valid surfing (owner policy, cycle 14). Free perception signals (box aspect,
  displacement, compensated motion) do not separate 0155 from valid rides (cycles 8, 13, 14: 0155 moves 1.0–2.6
  body heights/s relative to the lineup while carried in a pop-up crouch).
- **Code under test:** `pipeline/action_validity.py` (prompt `action-validity-v2`, `parse_observations`, `decide`),
  profile `pipeline/sport_profiles/surfing.py` `action_validity` (established = prone / kneeling / standing riding,
  transitional = popping_up, min_established_sec 2.0 — set a priori, not fitted).
- **What changes vs EXP-08-001:** the model only OBSERVES a per-frame state from a fixed vocabulary; the verdict is
  computed in code; two independent passes (different frame offsets) must agree for VALID or INVALID; any
  disagreement / low confidence / unparsable answer is UNCERTAIN (review, never VALID); target crops (tracked box
  + 50 % margin, 384 px) instead of a whole-frame proxy.
- **Input (frozen, development split — NOT holdout):** the 25 selected windows of run 44388634790 (sidecar target
  tracks) + GT controls: 0155 (failed take-off, GT exclude), 0108 tail 6.8–9.2 s, 0094 track-37 tail 13.2–22.5 s.
- **Sampling:** 12 crops per pass at 0.5 s from window start (pass A offset 0.0 s, pass B offset 0.25 s).
- **Model:** gemini-2.5-flash, temperature 0, one image per call; no verdict cache across runs.
- **Metrics:** FP = GT-valid window INVALID; withheld = GT-valid window UNCERTAIN; 0155 verdict; agreement rate.
- **Failure conditions (any → gate stays OFF):** ≥ 1 GT-valid window INVALID; 0155 VALID; > 2 of 23 GT-valid windows
  UNCERTAIN (each is a withheld-correct reel); < 80 % pass agreement.
- **Success:** 0155 INVALID (or UNCERTAIN → review) with 0 FP and ≤ 2 UNCERTAIN valid windows. Even then this is
  development evidence (0155 is a known case); the gate may only be enabled for a strict cold run, and blind
  generalization stays BLOCKED until new labelled footage with failed attempts exists.
- **Cost cap:** $0.40 hard (≈ 54 calls × ~$0.002–0.006); from the remaining cycle budget of ≈ $1.519.
- **No production effect:** evaluation workflow only, read-only R2 proxies, JSON verdicts only, no publication.
