# Primary-Actor Continuity Policy

## Decision

SportReel no longer treats the number of visible people as a quality gate.

A personal highlight is valid when the athlete performing the action remains
reliably attributable from setup through execution and outcome. Teammates,
opponents, officials, surfers in the lineup, racers, and bystanders may remain
visible when they do not make the primary action ambiguous.

## Cross-sport examples

### Surfing

Allowed:

- the target surfer completes a ride while another surfer waits in the background;
- another person paddles at the edge of the frame;
- a lineup is visible behind the target, but the target remains continuously clear.

Blocked or trimmed:

- the camera switches from one surfer to another during the ride;
- two surfers are both active and the system cannot attribute the move;
- the target is materially obscured at the key maneuver;
- identity continuity is uncertain.

### Football and other team sports

Allowed:

- a player dribbles through defenders;
- a scorer remains the clear actor while teammates and opponents surround the play;
- a tackler, passer, goalkeeper, or shooter is clearly attributable within a group play.

Blocked or trimmed:

- the system cannot determine which player completed the action;
- tracking changes from one player to another;
- the key action is hidden and attribution is speculative;
- multiple active players compete for primary focus without a reliable target.

## Selection contract

For every selected event the analyzer records:

- `primary_actor_clear`;
- `primary_actor_confidence`;
- `identity_continuity`;
- `background_people_present`;
- `competing_active_subjects`;
- `target_occluded_at_key_moment`;
- `primary_actor_reason`.

Presence of background people is explicitly non-blocking. Blocking reasons are
restricted to:

- `PRIMARY_ACTOR_UNCLEAR`;
- `IDENTITY_SWITCH`;
- `PRIMARY_ACTOR_OCCLUDED`;
- existing independent defects such as `IDENTITY_MISMATCH`.

If a wide event is ambiguous but contains a complete focused sub-window of at
least six seconds, the focused sub-window may be selected instead.

## Athlete coverage contract

A background-only detection is not an athlete cluster. A confirmed cluster begins
when the selector emits at least one action candidate.

Every confirmed athlete cluster must have one of these outcomes:

- `draft_created`;
- `no_complete_action`;
- `quality_below_threshold`;
- `target_not_trackable`;
- `primary_actor_uncertain`;
- `duplicate_identity_cluster`;
- an explicit unresolved coverage gap requiring further correction.

The diagnostics artifact `athlete_coverage_report.json` reports:

- confirmed athlete clusters;
- clusters represented in drafts;
- athlete draft coverage rate;
- athlete accountability rate;
- candidate and selected action seconds;
- action source utilization rate;
- each selected and rejected window with its reason.

## Acceptance criteria

A production run should demonstrate:

1. Crowded but attributable surfing and football events pass the prefilter.
2. Genuine identity switches and uncertain attribution remain blocked.
3. Every confirmed athlete cluster has a draft or an explicit no-output reason.
4. `athlete_coverage_report.json` is present in diagnostics.
5. Source utilization and athlete coverage improve without increasing identity
   mismatch or mixed-athlete defects.
