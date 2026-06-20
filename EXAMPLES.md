# Examples

## Drift Risk: Advisory vs Deterministic

### Old Advisory

```json
{
  "state_context": {
    "current": "drift_risk",
    "previous": null,
    "changed_recently": false,
    "hours_in_current_state": null
  },
  "whoop_data": {
    "recovery_score": 34,
    "sleep_hours": 7.1,
    "sleep_efficiency": 95.9,
    "hrv": 41.1,
    "resting_hr": 68,
    "state": "drift_risk",
    "reasoning": "low recovery, decent sleep, no clear commitment anchor"
  },
  "recommendation": {
    "can_send": true,
    "suggested_type": "light_checkin",
    "context": "Advisory only; assistant must interpret this loosely."
  }
}
```

Actual loose message:

```text
Recovery looks a little low today. Maybe keep things light. Want to focus on one thing?
```

### Deterministic Policy

```json
{
  "decision_id": "2026-06-19T13:00:00_drift_risk_structure_prompt",
  "state": "drift_risk",
  "inputs": {
    "recovery_score": 34,
    "sleep_hours": 7.1,
    "sleep_efficiency": 95.9,
    "hrv": 41.1,
    "resting_hr": 68,
    "calendar_buffer_hours": null,
    "unanswered_checkins": 0,
    "trigger_source": "midday_check"
  },
  "policy": {
    "allow_message": true,
    "message_type": "structure_prompt",
    "tone": "direct_gentle",
    "max_items": 1,
    "blocked_behaviors": ["large_task_dump", "generic_motivation", "ambitious_push", "repeated_checkin"],
    "required_actions": ["log_policy_decision", "record_checkin_if_sent"]
  },
  "approved_message": {
    "text": "Recovery is 34% and there is no calendar anchor. Pick one thing to move now.",
    "choices": ["Deep work block", "Admin cleanup", "Recovery reset"]
  },
  "audit": {
    "logged": true,
    "verification_status": "Verified Log"
  }
}
```

Actual gated message:

```text
Recovery is 34% and there is no calendar anchor. Pick one: deep work block, admin cleanup, or recovery reset.
```

## Other States

- `urgent`: suppress normal check-ins; critical only.
- `anchored`: allow one light task or commitment reminder.
- `high_drift_risk`: allow only gentle recovery-aware prompting.
- `primed`: protect focus and suggest one hard-work block.
- `unknown`: stay conservative and silent by default.
