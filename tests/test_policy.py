from __future__ import annotations

import unittest

from whoop_policy_layer.policy import build_policy_contract, simulated_inputs


class PolicyTests(unittest.TestCase):
    def test_drift_risk_structure_prompt(self) -> None:
        result = build_policy_contract(simulated_inputs("drift_risk"), trigger_source="test")
        self.assertEqual(result["state"], "drift_risk")
        self.assertTrue(result["policy"]["allow_message"])
        self.assertEqual(result["policy"]["message_type"], "structure_prompt")
        self.assertEqual(result["policy"]["max_items"], 1)
        self.assertIn("large_task_dump", result["policy"]["blocked_behaviors"])

    def test_high_drift_blocks_ambitious_push(self) -> None:
        result = build_policy_contract(simulated_inputs("high_drift_risk"), trigger_source="test")
        self.assertEqual(result["state"], "high_drift_risk")
        self.assertEqual(result["policy"]["message_type"], "recovery_prompt")
        self.assertIn("ambitious_push", result["policy"]["blocked_behaviors"])

    def test_primed_deep_work(self) -> None:
        result = build_policy_contract(simulated_inputs("primed"), trigger_source="test")
        self.assertEqual(result["state"], "primed")
        self.assertEqual(result["policy"]["message_type"], "deep_work_prompt")
        self.assertIn("routine_admin_nudge", result["policy"]["blocked_behaviors"])

    def test_urgent_silent_unless_critical(self) -> None:
        result = build_policy_contract(simulated_inputs("urgent"), trigger_source="routine")
        self.assertEqual(result["state"], "urgent")
        self.assertFalse(result["policy"]["allow_message"])

    def test_unknown_conservative(self) -> None:
        result = build_policy_contract(simulated_inputs("unknown"), trigger_source="test")
        self.assertEqual(result["state"], "unknown")
        self.assertFalse(result["policy"]["allow_message"])


if __name__ == "__main__":
    unittest.main()
