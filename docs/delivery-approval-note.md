# Delivery approval note

The Review screen approval flow should preserve the visible draft name and show the delivery result end to end.

Current contract:

- The app sends the draft identifier and visible draft name when approving.
- The API accepts older app builds that send only the identifier.
- When the visible name is missing, the API reads it from Drive before moving the draft.
- The delivery status row stores the resolved name so the operator can diagnose the approval later.
- A successful approval response tells the app whether delivery started and includes the delivery run identifier.
- The Review screen must not say approval will run on the next pipeline run. Approval starts delivery immediately when the API reports that it started.

Verification:

1. Approve a draft from Review.
2. Confirm the created `delivery_runs` row includes the visible draft name.
3. Confirm the Review success alert says delivery started and includes the delivery run prefix.
4. Confirm the Delivery status card shows the draft name and not only an ID prefix.
5. Confirm older clients still work when they submit only the draft identifier.
6. Confirm an approval response with delivery not started does not appear as a successful delivery start.
