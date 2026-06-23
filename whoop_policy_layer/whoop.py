"""WHOOP OAuth and API client."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from typing import Any

from whoop_policy_layer.config import (
    WHOOP_API_BASE,
    WHOOP_CLIENT_ID,
    WHOOP_CLIENT_SECRET,
    WHOOP_REDIRECT_URI,
    WHOOP_TOKEN_URL,
)
from whoop_policy_layer.storage import Storage


FINALIZATION_DELAY_MINUTES = int(os.getenv("WHOOP_FINALIZATION_DELAY_MINUTES", "30") or "30")


def _aiohttp():
    try:
        import aiohttp
    except ImportError as error:
        raise RuntimeError("aiohttp is required for live WHOOP API calls. Install requirements.txt.") from error
    return aiohttp


def expires_at_from_response(payload: dict[str, Any]) -> str:
    seconds = int(payload.get("expires_in") or 3600)
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).replace(microsecond=0).isoformat()


def is_expiring(expires_at: str | None, window_seconds: int = 300) -> bool:
    if not expires_at:
        return True
    try:
        expiry = datetime.fromisoformat(expires_at)
    except ValueError:
        return True
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return expiry <= datetime.now(timezone.utc) + timedelta(seconds=window_seconds)


class WhoopClient:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    async def exchange_code(self, code: str) -> dict[str, Any]:
        aiohttp = _aiohttp()
        async with aiohttp.ClientSession() as session:
            async with session.post(
                WHOOP_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": WHOOP_REDIRECT_URI,
                    "client_id": WHOOP_CLIENT_ID,
                    "client_secret": WHOOP_CLIENT_SECRET,
                },
            ) as response:
                payload = await response.json()
                if response.status >= 400:
                    raise RuntimeError(f"WHOOP token exchange failed: {payload}")
        payload["expires_at"] = expires_at_from_response(payload)
        self.storage.save_token(payload)
        return payload

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        aiohttp = _aiohttp()
        async with aiohttp.ClientSession() as session:
            async with session.post(
                WHOOP_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": WHOOP_CLIENT_ID,
                    "client_secret": WHOOP_CLIENT_SECRET,
                },
            ) as response:
                payload = await response.json()
                if response.status >= 400:
                    raise RuntimeError(f"WHOOP token refresh failed: {payload}")
        payload["expires_at"] = expires_at_from_response(payload)
        payload.setdefault("refresh_token", refresh_token)
        self.storage.save_token(payload)
        return payload

    async def token(self) -> dict[str, Any] | None:
        token = self.storage.get_token()
        if not token:
            return None
        if is_expiring(token.get("expires_at")) and token.get("refresh_token"):
            return await self.refresh(token["refresh_token"])
        return token

    async def request(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        token = await self.token()
        if not token:
            raise RuntimeError("WHOOP is not connected. Visit /oauth/whoop/start.")
        aiohttp = _aiohttp()
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{WHOOP_API_BASE}{path}",
                params=params or {},
                headers={"Authorization": f"Bearer {token['access_token']}"},
            ) as response:
                payload = await response.json()
                if response.status >= 400:
                    raise RuntimeError(f"WHOOP API request failed: {payload}")
                return payload

    async def latest_context_inputs(self) -> dict[str, Any]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=7)
        recovery_payload = await self.request("/v2/recovery", {"start": start.isoformat(), "end": end.isoformat(), "limit": 5})
        sleep_payload = await self.request("/v2/activity/sleep", {"start": start.isoformat(), "end": end.isoformat(), "limit": 5})
        selected = select_stable_whoop_records(
            recovery_payload.get("records") or [],
            sleep_payload.get("records") or [],
            now=end,
        )
        metadata = selected["metadata"]
        if metadata["whoop_data_freshness"] != "finalized_current":
            return {
                "recovery_score": None,
                "hrv": None,
                "resting_hr": None,
                "sleep_hours": None,
                "sleep_efficiency": None,
                "state": "unknown",
                "reasoning": f"WHOOP data is {metadata['whoop_data_freshness']}; waiting for finalized SCORED sleep/recovery.",
                "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                **metadata,
            }
        recovery = selected["recovery"] or {}
        sleep = selected["sleep"] or {}
        score = recovery.get("score", {}) if recovery else {}
        sleep_score = sleep.get("score", {}) if sleep else {}
        stage_summary = sleep_score.get("stage_summary", {})
        sleep_seconds = sleep_score.get("sleep_needed", {}).get("baseline_milli") or sleep_score.get("sleep_performance_percentage")
        return {
            "recovery_score": score.get("recovery_score"),
            "hrv": score.get("hrv_rmssd_milli"),
            "resting_hr": score.get("resting_heart_rate"),
            "sleep_hours": _sleep_hours(sleep, sleep_seconds),
            "sleep_efficiency": sleep_score.get("sleep_efficiency_percentage") or sleep_score.get("sleep_performance_percentage"),
            "reasoning": "live WHOOP recovery and sleep data",
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            **metadata,
            "raw_dates": {
                "recovery": recovery.get("created_at") if recovery else None,
                "sleep": sleep.get("created_at") if sleep else None,
            },
        }


def _first_record(payload: dict[str, Any]) -> dict[str, Any]:
    records = payload.get("records") or []
    return records[0] if records else {}


def _parse_whoop_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _score_state(record: dict[str, Any] | None) -> str:
    return str((record or {}).get("score_state") or "").upper()


def _is_scored(record: dict[str, Any] | None) -> bool:
    return _score_state(record) == "SCORED"


def _is_nap(sleep: dict[str, Any] | None) -> bool:
    return bool((sleep or {}).get("nap"))


def _sleep_end(sleep: dict[str, Any] | None) -> datetime | None:
    return _parse_whoop_datetime((sleep or {}).get("end"))


def _sleep_sort_key(sleep: dict[str, Any]) -> datetime:
    return _sleep_end(sleep) or _parse_whoop_datetime(sleep.get("start")) or datetime.min.replace(tzinfo=timezone.utc)


def _recovery_sort_key(recovery: dict[str, Any]) -> datetime:
    return (
        _parse_whoop_datetime(recovery.get("created_at"))
        or _parse_whoop_datetime(recovery.get("updated_at"))
        or datetime.min.replace(tzinfo=timezone.utc)
    )


def select_stable_whoop_records(
    recovery_records: list[dict[str, Any]],
    sleep_records: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    finalization_delay_minutes: int = FINALIZATION_DELAY_MINUTES,
) -> dict[str, Any]:
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    ordered_sleeps = sorted(sleep_records or [], key=_sleep_sort_key, reverse=True)
    non_naps = [item for item in ordered_sleeps if not _is_nap(item)]
    latest_sleep = (non_naps or ordered_sleeps or [None])[0]
    metadata = {
        "sleep_score_state": _score_state(latest_sleep) if latest_sleep else None,
        "sleep_id": latest_sleep.get("id") if latest_sleep else None,
        "sleep_end": latest_sleep.get("end") if latest_sleep else None,
        "finalization_delay_minutes": finalization_delay_minutes,
        "recovery_score_state": None,
        "recovery_sleep_id": None,
        "classification_source": None,
        "whoop_data_freshness": "missing",
    }
    if not latest_sleep:
        return {"sleep": None, "recovery": None, "metadata": metadata}
    if not _is_scored(latest_sleep):
        metadata["whoop_data_freshness"] = "pending_score"
        return {"sleep": latest_sleep, "recovery": None, "metadata": metadata}
    end_time = _sleep_end(latest_sleep)
    if end_time and (current_time - end_time).total_seconds() / 60 < finalization_delay_minutes:
        metadata["whoop_data_freshness"] = "too_fresh"
        return {"sleep": latest_sleep, "recovery": None, "metadata": metadata}
    recoveries = sorted(recovery_records or [], key=_recovery_sort_key, reverse=True)
    matches = [
        item for item in recoveries
        if latest_sleep.get("id") and str(item.get("sleep_id") or "") == str(latest_sleep.get("id"))
    ]
    selected_recovery = matches[0] if matches else None
    metadata["recovery_score_state"] = _score_state(selected_recovery) if selected_recovery else None
    metadata["recovery_sleep_id"] = selected_recovery.get("sleep_id") if selected_recovery else None
    if not selected_recovery:
        metadata["whoop_data_freshness"] = "missing"
        return {"sleep": latest_sleep, "recovery": None, "metadata": metadata}
    if not _is_scored(selected_recovery):
        metadata["whoop_data_freshness"] = "pending_score"
        return {"sleep": latest_sleep, "recovery": selected_recovery, "metadata": metadata}
    metadata["whoop_data_freshness"] = "finalized_current"
    metadata["classification_source"] = "current_finalized"
    return {"sleep": latest_sleep, "recovery": selected_recovery, "metadata": metadata}


def _sleep_hours(sleep: dict[str, Any], fallback: Any = None) -> float | None:
    score = sleep.get("score", {}) if sleep else {}
    stage = score.get("stage_summary", {})
    total_ms = stage.get("total_in_bed_time_milli") or stage.get("total_sleep_time_milli")
    if total_ms:
        return round(float(total_ms) / 1000 / 3600, 2)
    if isinstance(fallback, (int, float)) and fallback > 10000:
        return round(float(fallback) / 1000 / 3600, 2)
    return None
