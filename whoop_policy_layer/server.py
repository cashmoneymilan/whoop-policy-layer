"""HTTP and MCP service for the public WHOOP policy layer."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from whoop_policy_layer import __version__
from whoop_policy_layer.config import PUBLIC_BASE_URL, WHOOP_AUTH_URL, WHOOP_CLIENT_ID, WHOOP_REDIRECT_URI, WHOOP_SCOPE
from whoop_policy_layer.policy import advisory_context, build_policy_contract, classify_state, simulated_inputs
from whoop_policy_layer.storage import Storage
from whoop_policy_layer.whoop import WhoopClient


oauth_states: dict[str, datetime] = {}
storage = Storage()
whoop = WhoopClient(storage)

TOOLS = [
    {
        "name": "get_whoop_context",
        "title": "Get WHOOP Context",
        "description": "Return old advisory WHOOP context: state_context, whoop_data, and loose recommendation.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_behavior_policy",
        "title": "Get Behavior Policy",
        "description": "Return and log the deterministic assistant behavior policy contract from WHOOP data.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trigger_source": {"type": "string"},
                "calendar_buffer_hours": {"type": "number"},
                "unanswered_checkins": {"type": "number"},
            },
        },
    },
    {
        "name": "record_policy_outcome",
        "title": "Record Policy Outcome",
        "description": "Record whether the assistant sent or skipped the approved policy message.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "decision_id": {"type": "string"},
                "sent": {"type": "boolean"},
                "checkin_id": {"type": "string"},
                "outcome_note": {"type": "string"},
            },
            "required": ["decision_id", "sent"],
        },
    },
    {
        "name": "simulate_policy",
        "title": "Simulate Policy",
        "description": "Return a deterministic demo policy without WHOOP credentials.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "enum": ["urgent", "anchored", "drift_risk", "high_drift_risk", "primed", "unknown"]},
                "trigger_source": {"type": "string"},
            },
        },
    },
]


async def health(_: Request) -> JSONResponse:
    token = storage.get_token()
    return JSONResponse(
        {
            "ok": True,
            "service": "whoop-policy-layer",
            "version": __version__,
            "whoop_connected": bool(token),
            "endpoints": {
                "oauth_start": "/oauth/whoop/start",
                "context": "/api/context",
                "policy": "/api/policy",
                "mcp": "/mcp",
                "demo": "/demo/drift-risk",
            },
        }
    )


async def token_status(_: Request) -> JSONResponse:
    token = storage.get_token()
    if not token:
        return JSONResponse({"connected": False, "message": "No token found. Visit /oauth/whoop/start."})
    return JSONResponse(
        {
            "connected": True,
            "expires_at": token.get("expires_at"),
            "scope": token.get("scope"),
            "updated_at": token.get("updated_at"),
        }
    )


async def oauth_start(_: Request) -> RedirectResponse:
    state = secrets.token_urlsafe(24)
    oauth_states[state] = datetime.now(timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    for key, created in list(oauth_states.items()):
        if created < cutoff:
            del oauth_states[key]
    params = {
        "client_id": WHOOP_CLIENT_ID,
        "redirect_uri": WHOOP_REDIRECT_URI,
        "response_type": "code",
        "scope": WHOOP_SCOPE,
        "state": state,
    }
    return RedirectResponse(f"{WHOOP_AUTH_URL}?{urlencode(params)}")


async def oauth_callback(request: Request) -> JSONResponse:
    error = request.query_params.get("error")
    if error:
        return JSONResponse({"error": error}, status_code=400)
    state = request.query_params.get("state")
    code = request.query_params.get("code")
    if not state or state not in oauth_states:
        return JSONResponse({"error": "invalid_state"}, status_code=400)
    if not code:
        return JSONResponse({"error": "missing_code"}, status_code=400)
    del oauth_states[state]
    await whoop.exchange_code(code)
    return JSONResponse({"ok": True, "message": "WHOOP connected. You can close this tab.", "health": f"{PUBLIC_BASE_URL}/health"})


async def live_inputs(request: Request) -> dict[str, Any]:
    inputs = await whoop.latest_context_inputs()
    if request.query_params.get("calendar_buffer_hours"):
        inputs["calendar_buffer_hours"] = float(request.query_params["calendar_buffer_hours"])
    if request.query_params.get("unanswered_checkins"):
        inputs["unanswered_checkins"] = int(request.query_params["unanswered_checkins"])
    return inputs


async def api_context(request: Request) -> JSONResponse:
    try:
        inputs = await live_inputs(request)
    except Exception as error:
        return JSONResponse({"error": str(error), "state_context": {"current": "unknown"}}, status_code=503)
    state = classify_state(
        recovery_score=inputs.get("recovery_score"),
        sleep_efficiency=inputs.get("sleep_efficiency"),
        calendar_buffer_hours=inputs.get("calendar_buffer_hours"),
    )
    return JSONResponse(advisory_context(inputs, state))


async def api_policy(request: Request) -> JSONResponse:
    trigger_source = request.query_params.get("trigger_source") or "api"
    try:
        inputs = await live_inputs(request)
    except Exception as error:
        inputs = {"reasoning": str(error)}
    contract = build_policy_contract(inputs, trigger_source=trigger_source)
    return JSONResponse(storage.log_decision(contract, trigger_source=trigger_source))


async def record_outcome(request: Request) -> JSONResponse:
    payload = await request.json()
    return JSONResponse(
        storage.record_outcome(
            decision_id=str(payload.get("decision_id") or ""),
            sent=bool(payload.get("sent")),
            checkin_id=str(payload.get("checkin_id") or ""),
            outcome_note=str(payload.get("outcome_note") or ""),
        )
    )


async def demo_drift_risk(_: Request) -> JSONResponse:
    contract = build_policy_contract(simulated_inputs("drift_risk"), trigger_source="demo", log_preview=False)
    return JSONResponse({"advisory": advisory_context(simulated_inputs("drift_risk"), "drift_risk"), "policy": contract})


def rpc_result(request_id: Any, result: Any) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})


def rpc_error(request_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "get_whoop_context":
        inputs = await whoop.latest_context_inputs()
        state = classify_state(
            recovery_score=inputs.get("recovery_score"),
            sleep_efficiency=inputs.get("sleep_efficiency"),
            calendar_buffer_hours=arguments.get("calendar_buffer_hours"),
        )
        result = advisory_context(inputs, state)
    elif name == "get_behavior_policy":
        inputs = await whoop.latest_context_inputs()
        if arguments.get("calendar_buffer_hours") is not None:
            inputs["calendar_buffer_hours"] = arguments.get("calendar_buffer_hours")
        if arguments.get("unanswered_checkins") is not None:
            inputs["unanswered_checkins"] = arguments.get("unanswered_checkins")
        contract = build_policy_contract(inputs, trigger_source=str(arguments.get("trigger_source") or "mcp"))
        result = storage.log_decision(contract, trigger_source=str(arguments.get("trigger_source") or "mcp"))
    elif name == "record_policy_outcome":
        result = storage.record_outcome(
            decision_id=str(arguments.get("decision_id") or ""),
            sent=bool(arguments.get("sent")),
            checkin_id=str(arguments.get("checkin_id") or ""),
            outcome_note=str(arguments.get("outcome_note") or ""),
        )
    elif name == "simulate_policy":
        state = str(arguments.get("state") or "drift_risk")
        result = build_policy_contract(simulated_inputs(state), trigger_source=str(arguments.get("trigger_source") or "simulate"))
    else:
        raise ValueError(f"Unknown tool: {name}")
    return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}


async def mcp_endpoint(request: Request) -> Response:
    if request.method == "GET":
        return Response("event: endpoint\ndata: ready\n\n", media_type="text/event-stream")
    payload = await request.json()
    request_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}
    if method == "initialize":
        return rpc_result(
            request_id,
            {
                "protocolVersion": params.get("protocolVersion") or "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "whoop-policy-layer", "version": __version__},
            },
        )
    if method == "notifications/initialized":
        return Response(status_code=202)
    if method == "tools/list":
        return rpc_result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        try:
            result = await call_tool(str(params.get("name") or ""), params.get("arguments") or {})
            return rpc_result(request_id, result)
        except Exception as error:
            return rpc_error(request_id, -32000, str(error))
    return rpc_error(request_id, -32601, f"Unknown method: {method}")


app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/token-status", token_status, methods=["GET"]),
        Route("/oauth/whoop/start", oauth_start, methods=["GET"]),
        Route("/oauth/whoop/callback", oauth_callback, methods=["GET"]),
        Route("/api/context", api_context, methods=["GET"]),
        Route("/api/policy", api_policy, methods=["GET"]),
        Route("/api/record-outcome", record_outcome, methods=["POST"]),
        Route("/demo/drift-risk", demo_drift_risk, methods=["GET"]),
        Route("/mcp", mcp_endpoint, methods=["GET", "POST"]),
    ]
)


def main() -> None:
    import uvicorn

    from whoop_policy_layer.config import HOST, PORT

    uvicorn.run("whoop_policy_layer.server:app", host=HOST, port=PORT)


if __name__ == "__main__":
    main()
