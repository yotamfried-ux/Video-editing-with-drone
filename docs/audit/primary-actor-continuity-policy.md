# Primary-Athlete Continuity Policy

## Decision

SportReel does not treat the number of visible or active people as a quality gate.

A personal reel is **centered on one featured athlete**. It is valid when that athlete remains reliably attributable from setup through execution and outcome. Teammates, opponents, officials, other surfers, racers, and bystanders may remain visible or actively participate when they do not displace the featured athlete as the clear center of the action.

The contract is not “one person in the frame.” The contract is:

```text
one featured athlete
+ stable identity and tracking
+ clear ownership of the selected action
+ other people allowed as sport context
```

## Cross-sport examples

### Surfing

Allowed:

- the target surfer completes a ride while another surfer waits in the background;
- another person paddles at the edge of the frame;
- a lineup is visible behind the target;
- another surfer enters or rides the same wave while the target surfer remains central, continuous, and clearly attributable;
- both surfers are active, but the edit and tracker remain locked to the target athlete.

Blocked or trimmed:

- the camera switches from the target surfer to the other surfer during the ride;
- two surfers are active and the system cannot determine which one owns the selected maneuver;
- the target is materially obscured at the key maneuver;
- identity continuity is uncertain;
- the other surfer becomes the camera's primary subject and the target is lost.

### Football and other team sports

Allowed:

- a player dribbles through defenders;
- a scorer remains the clear actor while teammates and opponents surround the play;
- a tackler, passer, goalkeeper, or shooter is clearly attributable within a group play;
- several players actively contest the ball while the featured player's action remains readable and central.

Blocked or trimmed:

- the system cannot determine which player completed the action;
- tracking changes from one player to another;
- the key action is hidden and attribution is speculative;
- multiple active players compete for primary focus and no reliable featured athlete can be established.

## Selection contract

For every selected event the analyzer records:

- `primary_actor_clear`;
- `primary_actor_confidence`;
- `identity_continuity`;
- `background_people_present`;
- `multiple_active_subjects`;
- `competing_active_subjects`;
- `target_occluded_at_key_moment`;
- `primary_actor_reason`.

`background_people_present:true`, `multiple_active_subjects:true`, and `competing_active_subjects:true` are explicitly non-blocking when:

- `primary_actor_clear:true`;
- identity continuity is stable;
- target confidence is acceptable;
- the target athlete owns the selected action;
- sidecar continuity confirms that the target remains followable.

Blocking reasons are restricted to genuine target uncertainty:

- `PRIMARY_ACTOR_UNCLEAR`;
- `IDENTITY_SWITCH`;
- `PRIMARY_ACTOR_OCCLUDED`;
- existing independent defects such as `IDENTITY_MISMATCH`.

If a wide event is ambiguous but contains a complete focused sub-window of at least six seconds, the focused sub-window may be selected instead.

## Athlete coverage contract

A background-only detection is not an athlete cluster. A confirmed cluster begins when the selector emits at least one action candidate.

Every confirmed athlete cluster must have one of these outcomes:

- `draft_created`;
- `no_complete_action`;
- `quality_below_threshold`;
- `target_not_trackable`;
- `primary_actor_uncertain`;
- `duplicate_action_window`;
- `duplicate_identity_cluster`;
- an explicit unresolved coverage gap requiring further correction.

`duplicate_action_window` means the athlete was represented by another selected window covering the same physical action. `duplicate_identity_cluster` means two identity clusters were reconciled as the same athlete.

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

1. Crowded but attributable football actions pass.
2. A surf ride with another surfer on the same wave passes when the target remains central.
3. The same cases fail when identity, target tracking, or action ownership becomes uncertain.
4. Every confirmed athlete cluster has a draft or an explicit no-output reason.
5. `athlete_coverage_report.json` is present in diagnostics.
6. Source utilization and athlete coverage improve without increasing identity mismatch or genuine mixed-athlete defects.
