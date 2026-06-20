"""WHOOP OAuth and API client."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from whoop_policy_layer.config import (
    WHOOP_API_BASE,
    WHOOP_CLIENT_ID,
    WHOOP_CLIENT_SECRET,
    WHOOP_REDIRECT_URI,
    WHOOP_TOKEN_URL,
)
from whoop_policy_layer.storage import Storage


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
        recovery_payload = await self.request("/v2/recovery", {"start": start.isoformat(), "end": end.isoformat(), "limit": 1})
        sleep_payload = await self.request("/v2/activity/sleep", {"start": start.isoformat(), "end": end.isoformat(), "limit": 1})
        recovery = _first_record(recovery_payload)
        sleep = _first_record(sleep_payload)
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
            "raw_dates": {
                "recovery": recovery.get("created_at") if recovery else None,
                "sleep": sleep.get("created_at") if sleep else None,
            },
        }


def _first_record(payload: dict[str, Any]) -> dict[str, Any]:
    records = payload.get("records") or []
    return records[0] if records else {}


def _sleep_hours(sleep: dict[str, Any], fallback: Any = None) -> float | None:
    score = sleep.get("score", {}) if sleep else {}
    stage = score.get("stage_summary", {})
    total_ms = stage.get("total_in_bed_time_milli") or stage.get("total_sleep_time_milli")
    if total_ms:
        return round(float(total_ms) / 1000 / 3600, 2)
    if isinstance(fallback, (int, float)) and fallback > 10000:
        return round(float(fallback) / 1000 / 3600, 2)
    return None
