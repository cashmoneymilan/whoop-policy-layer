from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TMP_DB = Path(tempfile.gettempdir()) / "whoop-policy-layer-verify.sqlite3"

os.environ["DATABASE_URL"] = f"sqlite:///{TMP_DB}"
os.environ.setdefault("PUBLIC_BASE_URL", "http://localhost:8080")
sys.path.insert(0, str(ROOT))


def print_result(name: str, passed: bool, detail: str = "") -> None:
    status = "PASS" if passed else "FAIL"
    suffix = f" - {detail}" if detail else ""
    print(f"{status}: {name}{suffix}")


def require(name: str, condition: bool, detail: str = "") -> None:
    print_result(name, condition, detail)
    if not condition:
        raise AssertionError(name)


def run_unittests() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
    require("unit test suite passes", result.returncode == 0)


def decode_tool_text(response_json: dict) -> dict:
    text = response_json["result"]["content"][0]["text"]
    return json.loads(text)


def run_api_checks() -> None:
    if TMP_DB.exists():
        TMP_DB.unlink()

    from starlette.testclient import TestClient

    from whoop_policy_layer.server import app

    client = TestClient(app)

    health = client.get("/health")
    health_json = health.json()
    require("GET /health returns 200", health.status_code == 200)
    require("GET /health identifies service", health_json.get("service") == "whoop-policy-layer")
    require("GET /health exposes MCP endpoint", health_json.get("endpoints", {}).get("mcp") == "/mcp")

    token_status = client.get("/token-status")
    token_json = token_status.json()
    require("GET /token-status returns 200", token_status.status_code == 200)
    require("GET /token-status has safe connection status", "connected" in token_json and "access_token" not in token_json)

    demo = client.get("/demo/drift-risk")
    demo_json = demo.json()
    policy = demo_json["policy"]
    require("GET /demo/drift-risk returns 200", demo.status_code == 200)
    require("demo includes advisory context", "advisory" in demo_json)
    require("demo policy state is drift_risk", policy["state"] == "drift_risk")
    require("demo policy uses structure_prompt", policy["policy"]["message_type"] == "structure_prompt")
    require("demo blocks large task dumps", "large_task_dump" in policy["policy"]["blocked_behaviors"])
    require("demo is preview, not logged", policy["audit"]["logged"] is False)

    initialize = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
    )
    initialize_json = initialize.json()
    require("MCP initialize returns 200", initialize.status_code == 200)
    require("MCP initialize identifies server", initialize_json["result"]["serverInfo"]["name"] == "whoop-policy-layer")

    tools = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tool_names = [tool["name"] for tool in tools.json()["result"]["tools"]]
    require("MCP tools/list returns 200", tools.status_code == 200)
    require(
        "MCP exposes exactly four public tools",
        tool_names == ["get_whoop_context", "get_behavior_policy", "record_policy_outcome", "simulate_policy"],
        ", ".join(tool_names),
    )

    simulate = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "simulate_policy", "arguments": {"state": "primed"}},
        },
    )
    simulated = decode_tool_text(simulate.json())
    require("MCP simulate_policy returns 200", simulate.status_code == 200)
    require("MCP simulate_policy supports primed state", simulated["state"] == "primed")
    require("MCP simulate_policy emits deep_work_prompt", simulated["policy"]["message_type"] == "deep_work_prompt")

    live_policy = client.get("/api/policy?trigger_source=verify")
    live_json = live_policy.json()
    require("GET /api/policy returns 200 without WHOOP token", live_policy.status_code == 200)
    require("GET /api/policy returns decision_id", bool(live_json.get("decision_id")))
    require("GET /api/policy writes verified audit log", live_json["audit"]["verification_status"] == "Verified Log")

    outcome = client.post(
        "/api/record-outcome",
        json={"decision_id": live_json["decision_id"], "sent": False, "outcome_note": "verification skip"},
    )
    outcome_json = outcome.json()
    require("POST /api/record-outcome returns 200", outcome.status_code == 200)
    require("POST /api/record-outcome updates logged decision", outcome_json["status"] == "updated")

    oauth = client.get("/oauth/whoop/start", follow_redirects=False)
    location = oauth.headers.get("location", "")
    require("GET /oauth/whoop/start redirects", oauth.status_code in {302, 307})
    require("GET /oauth/whoop/start points at WHOOP OAuth", location.startswith("https://api.prod.whoop.com/oauth/oauth2/auth"))


def main() -> int:
    print("WHOOP Policy Layer verification")
    print(f"Project: {ROOT}")
    print(f"Temp DB: {TMP_DB}")
    run_unittests()
    run_api_checks()
    print("PASS: all verification checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
