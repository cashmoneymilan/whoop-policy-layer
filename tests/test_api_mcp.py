from __future__ import annotations

import unittest

from starlette.testclient import TestClient

from whoop_policy_layer.server import app


class ApiMcpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_health(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["service"], "whoop-policy-layer")

    def test_demo_drift_risk(self) -> None:
        response = self.client.get("/demo/drift-risk")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["policy"]["state"], "drift_risk")
        self.assertIn("advisory", data)

    def test_mcp_tools_list(self) -> None:
        response = self.client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        self.assertEqual(response.status_code, 200)
        tools = [tool["name"] for tool in response.json()["result"]["tools"]]
        self.assertEqual(
            tools,
            ["get_whoop_context", "get_behavior_policy", "record_policy_outcome", "simulate_policy"],
        )

    def test_mcp_simulate_policy(self) -> None:
        response = self.client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "simulate_policy", "arguments": {"state": "drift_risk"}},
            },
        )
        self.assertEqual(response.status_code, 200)
        text = response.json()["result"]["content"][0]["text"]
        self.assertIn("drift_risk", text)
        self.assertIn("structure_prompt", text)

    def test_record_outcome_without_prior_decision(self) -> None:
        response = self.client.post(
            "/api/record-outcome",
            json={"decision_id": "test-decision", "sent": False, "outcome_note": "test"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(response.json()["status"], {"created_without_prior_decision", "updated"})


if __name__ == "__main__":
    unittest.main()
