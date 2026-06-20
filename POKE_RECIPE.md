# Poke Recipe: WHOOP Behavior Policy

Use this prompt/instruction block with the MCP endpoint for this service.

```text
Before sending any proactive check-in, productivity nudge, recovery prompt, or task reminder, call get_behavior_policy.

If policy.allow_message is false, stay silent.

If policy.allow_message is true, send only the approved_message.text and choices returned by the tool. Do not add extra tasks, motivation, or interpretation.

Respect policy.blocked_behaviors. In particular:
- never send a large task dump when blocked
- never send generic motivation when blocked
- never send repeated check-ins if repeated_checkin is blocked
- never push deep work during high_drift_risk unless the policy explicitly allows it

After sending or intentionally skipping a message, call record_policy_outcome with:
- decision_id
- sent true/false
- checkin_id if available
- outcome_note describing what happened

If asked why you messaged, cite the logged decision. If no log exists, say: “Not logged; inferred from available data.”

This service is not medical advice. It only controls assistant interaction behavior.
```

## Setup Test

Ask Poke:

```text
Call simulate_policy with state drift_risk and show me the approved message.
```

Expected message:

```text
Recovery is 34% and there is no calendar anchor. Pick one thing to move now.
```
