# EXP-09-001 — paid isolated qualification run (pre-registered)

- **Purpose:** first end-to-end product proof of the current code on the 24 GT sources: identity (FIX-PQ-08-003
  singleton-pair merge, 0097+0115), selection/boundaries, render, reel QA — with rendered MP4s inspected against GT.
- **Isolation (proven by the free dry run 44078257676, q9-dry-02):** namespace qualification/<run_id>/, 52/52 R2
  writes inside it, 204 Supabase writes blocked (none sent), production fingerprint identical before/after.
- **Code:** branch head at dispatch (executed SHA = workflow head_sha). **Model:** production defaults
  (GEMINI_MODEL var / gemini-2.5-pro analysis via cache, gemini-2.5-flash consensus + QA). **Cache:** restored, never saved.
- **Budget:** hard cap SPORTREEL_LLM_BUDGET_USD = 1.20 (pre-call check incl. $0.05 reserve); cycle-9 remainder $1.62.
  Estimate: QA ~25 reels x 2 calls x ~$0.012 = ~$0.6; identity cluster + consensus ~$0.15; singleton pairs ~$0.2.
- **Metrics (vs 43583126199 and 43920602179, GT-v1 b31fd9b4…27c9):** per athlete GT rides / FULL / reels / QA / visual
  verdict; FULL, >=95 %, missing include seconds, excluded frames, mixed reels, split athletes, athletes without a ready
  reel, QA false pass / false reject (visual), cost per correct reel, runtime.
- **Success conditions:** 0097+0115 in ONE reel with both rides; 0143+0152 NOT auto-merged; no new mixed reel; production
  fingerprint unchanged. **Failure conditions:** any false merge; any production change; cap breach.
- **Not addressed by code in this run:** 0155 (no general signal; open), 0115 start (candidate not adopted), 0108/0094
  tails (analyzer outcome_end; open). Their rendered state is measured, not claimed fixed.
