# Delivery approval note

The Review screen approval flow should preserve the visible draft name end to end.

Current contract:

- The app sends the draft identifier and visible draft name when approving.
- The API accepts older app builds that send only the identifier.
- When the visible name is missing, the API reads it from Drive before moving the draft.
- The delivery status row stores the resolved name so the operator can diagnose the approval later.

Verification:

1. Approve a draft from Review.
2. Confirm the delivery status row includes the visible draft name.
3. Confirm the Delivery status card shows the name and not only a short identifier.
4. Confirm older clients still work when they submit only the draft identifier.
