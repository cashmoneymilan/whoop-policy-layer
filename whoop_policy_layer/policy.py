"""Deterministic assistant behavior policy from WHOOP context."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from whoop_policy_layer.config import (
    DEFAULT_BUFFER_ANCHORED_HOURS,
    DEFAULT_BUFFER_URGENT_HOURS,
    DEFAULT_RECOVERY_CRITICAL,
    DEFAULT_RECOVERY_HIGH,
    DEFAULT_RECOVERY_LOW,
    DEFAULT_SLEEP_EFFICIENCY_GOOD,
)


STATE_DEFAULTS: dict[str, dict[str, Any]] = {
    "urgent": {
        "allow_message": False,
        "message_type": "silent",
        "tone": "minimal",
        "max_items": 0,
        "allowed_urgency": "critical_only",
        "blocked_behaviors": ["routine_checkin", "large_task_dump", "generic_motivation", "admin_nudge"],
    },
    "anchored": {
        "allow_message": True,
        "message_type": "task_check",
        "tone": "direct_light",
        "max_items": 1,
        "allowed_urgency": "scheduled_or_light",
        "blocked_behaviors": ["large_task_dump", "generic_motivation"],
    },
    "drift_risk": {
        "allow_message": True,
        "message_type": "structure_prompt",
        "tone": "direct_gentle",
        "max_items": 1,
        "allowed_urgency": "decision_or_structure",
        "blocked_behaviors": ["large_task_dump", "generic_motivation", "ambitious_push", "repeated_checkin"],
    },
    "high_drift_risk": {
        "allow_message": True,
        "message_type": "recovery_prompt",
        "tone": "gentle_low_pressure",
        "max_items": 1,
        "allowed_urgency": "blocker_or_recovery",
        "blocked_behaviors": ["large_task_dump", "generic_motivation", "ambitious_push", "deep_work_push"],
    },
    "primed": {
        "allow_message": True,
        "message_type": "deep_work_prompt",
        "tone": "direct_protective",
        "max_items": 1,
        "allowed_urgency": "high_leverage",
        "blocked_behaviors": ["routine_admin_nudge", "generic_motivation", "large_task_dump"],
    },
    "unknown": {
        "allow_message": False,
        "message_type": "silent",
        "tone": "conservative",
        "max_items": 0,
        "allowed_urgency": "digest_only",
        "blocked_behaviors": ["proactive_checkin", "large_task_dump", "generic_motivation"],
    },
}

DEFAULT_CHOICES = ["Deep work block", "Admin cleanup", "Recovery reset"]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_state(
    *,
    recovery_score: float | None,
    sleep_efficiency: float | None,
    calendar_buffer_hours: float | None = None,
) -> str:
    if recovery_score is None:
        return "unknown"
    if calendar_buffer_hours is not None:
        if calendar_buffer_hours <= DEFAULT_BUFFER_URGENT_HOURS:
            return "urgent"
        if calendar_buffer_hours <= DEFAULT_BUFFER_ANCHORED_HOURS:
            return "anchored"
        if recovery_score < DEFAULT_RECOVERY_LOW:
            return "high_drift_risk"
        return "drift_risk"
    if recovery_score < DEFAULT_RECOVERY_CRITICAL:
        return "high_drift_risk"
    if recovery_score < DEFAULT_RECOVERY_LOW:
        return "drift_risk"
    if recovery_score >= DEFAULT_RECOVERY_HIGH and (
        sleep_efficiency is None or sleep_efficiency >= DEFAULT_SLEEP_EFFICIENCY_GOOD
    ):
        return "primed"
    return "anchored"


def advisory_context(inputs: dict[str, Any], state: str) -> dict[str, Any]:
    return {
        "state_context": {
            "current": state,
            "previous": inputs.get("previous_state"),
            "changed_recently": False,
            "hours_in_current_state": None,
        },
        "whoop_data": {
            "recovery_score": inputs.get("recovery_score"),
            "sleep_hours": inputs.get("sleep_hours"),
            "sleep_efficiency": inputs.get("sleep_efficiency"),
            "hrv": inputs.get("hrv"),
            "resting_hr": inputs.get("resting_hr"),
            "state": state,
            "reasoning": inputs.get("reasoning") or "classified from recovery, sleep, and optional calendar buffer",
        },
        "recommendation": {
            "can_send": state not in {"unknown", "urgent"},
            "suggested_type": "light_checkin" if state in {"drift_risk", "high_drift_risk"} else "task_check",
            "context": "Advisory only; assistant must interpret this loosely.",
        },
    }


def approved_message(state: str, policy: dict[str, Any], inputs: dict[str, Any], choices: list[str] | None = None) -> dict[str, Any]:
    if not policy.get("allow_message"):
        return {"text": "", "choices": []}
    options = (choices or DEFAULT_CHOICES)[:3]
    message_type = policy["message_type"]
    recovery = inputs.get("recovery_score")
    freshness = inputs.get("whoop_data_freshness")
    has_anchor = inputs.get("calendar_buffer_hours") is not None
    if message_type == "structure_prompt":
        anchor = "no calendar anchor" if not has_anchor else "a loose calendar anchor"
        if freshness and freshness != "finalized_current":
            recovery_text = "WHOOP is still finalizing sleep"
        else:
            recovery_text = f"Recovery is {recovery:.0f}%" if isinstance(recovery, (int, float)) else "Recovery is low"
        return {"text": f"{recovery_text} and there is {anchor}. Pick one thing to move now.", "choices": options}
    if message_type == "recovery_prompt":
        return {"text": "Low-capacity mode. Pick one low-pressure next step or call recovery.", "choices": options[:2] + ["Recovery block"]}
    if message_type == "deep_work_prompt":
        return {"text": "This looks like a high-capacity window. Protect one hard-work block.", "choices": options}
    if message_type == "task_check":
        return {"text": "Quick check: choose the one useful thing to move next.", "choices": options}
    if message_type == "critical_alert":
        return {"text": f"Critical item only: {options[0]}. Handle or explicitly defer it.", "choices": [options[0], "Defer"]}
    return {"text": "", "choices": []}


def build_policy_contract(
    inputs: dict[str, Any],
    *,
    trigger_source: str = "api",
    log_preview: bool = False,
    choices: list[str] | None = None,
) -> dict[str, Any]:
    normalized = {
        "recovery_score": num(inputs.get("recovery_score")),
        "sleep_hours": num(inputs.get("sleep_hours")),
        "sleep_efficiency": num(inputs.get("sleep_efficiency")),
        "hrv": num(inputs.get("hrv")),
        "resting_hr": num(inputs.get("resting_hr")),
        "calendar_buffer_hours": num(inputs.get("calendar_buffer_hours")),
        "unanswered_checkins": int(num(inputs.get("unanswered_checkins")) or 0),
        "trigger_source": trigger_source,
        "whoop_data_freshness": inputs.get("whoop_data_freshness"),
        "classification_source": inputs.get("classification_source"),
        "sleep_score_state": inputs.get("sleep_score_state"),
        "recovery_score_state": inputs.get("recovery_score_state"),
        "sleep_id": inputs.get("sleep_id"),
        "recovery_sleep_id": inputs.get("recovery_sleep_id"),
        "sleep_end": inputs.get("sleep_end"),
        "finalization_delay_minutes": inputs.get("finalization_delay_minutes"),
    }
    state = inputs.get("state") or classify_state(
        recovery_score=normalized["recovery_score"],
        sleep_efficiency=normalized["sleep_efficiency"],
        calendar_buffer_hours=normalized["calendar_buffer_hours"],
    )
    if state not in STATE_DEFAULTS:
        state = "unknown"
    policy = dict(STATE_DEFAULTS[state])
    policy["required_actions"] = ["log_policy_decision"]
    if policy["allow_message"]:
        policy["required_actions"].append("record_checkin_if_sent")
    if state == "urgent" and "critical" in trigger_source.lower():
        policy.update({"allow_message": True, "message_type": "critical_alert", "max_items": 1})
        policy["required_actions"] = ["log_policy_decision", "record_checkin_if_sent"]
    if normalized["unanswered_checkins"] >= 2 and policy["message_type"] not in {"critical_alert", "silent"}:
        policy.update({"allow_message": False, "message_type": "silent", "max_items": 0})
        policy["blocked_behaviors"] = list(policy["blocked_behaviors"]) + ["repeated_unanswered_checkin"]
        policy["required_actions"] = ["log_policy_decision"]
    timestamp = str(inputs.get("timestamp") or now_iso())[:19]
    decision_id = f"{timestamp}_{state}_{policy['message_type']}"
    return {
        "decision_id": decision_id,
        "state": state,
        "inputs": normalized,
        "policy": policy,
        "approved_message": approved_message(state, policy, normalized, choices),
        "audit": {
            "logged": bool(log_preview),
            "verification_status": "Verified Log" if log_preview else "Policy Preview - Not Logged",
        },
    }


def simulated_inputs(state: str = "drift_risk") -> dict[str, Any]:
    fixtures = {
        "urgent": {"recovery_score": 42, "sleep_hours": 5.5, "sleep_efficiency": 78, "calendar_buffer_hours": 0.75},
        "anchored": {"recovery_score": 65, "sleep_hours": 7.0, "sleep_efficiency": 88, "calendar_buffer_hours": 2.5},
        "drift_risk": {"recovery_score": 34, "sleep_hours": 7.1, "sleep_efficiency": 95.9, "hrv": 41.1, "resting_hr": 68},
        "high_drift_risk": {"recovery_score": 22, "sleep_hours": 4.6, "sleep_efficiency": 72, "hrv": 31, "resting_hr": 76},
        "primed": {"recovery_score": 86, "sleep_hours": 8.1, "sleep_efficiency": 92, "hrv": 58, "resting_hr": 55},
        "unknown": {},
    }
    return dict(fixtures.get(state, fixtures["drift_risk"]))
