import unittest

from fastapi.testclient import TestClient

from demo_app import create_app


class DemoAppTestCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())

    def test_sample_analysis_returns_structured_summary_and_quality_findings(self):
        response = self.client.get("/api/analyze/sample")

        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertIn("summary", payload)
        self.assertIn("quality_findings", payload)
        self.assertIn("source", payload)

        summary = payload["summary"]
        self.assertEqual(summary["problem_count"], 4)
        self.assertEqual(summary["medication_count"], 1)
        self.assertEqual(summary["allergy_count"], 0)
        self.assertGreaterEqual(len(summary["problems"]), 1)

        first_problem = summary["problems"][0]
        self.assertEqual(first_problem["display"], "Hypertension")
        self.assertEqual(first_problem["code"], "38341003")

        findings = payload["quality_findings"]
        self.assertGreaterEqual(len(findings), 1)
        self.assertTrue(
            any(finding["rule_id"] == "missing_allergy_list" for finding in findings)
        )


if __name__ == "__main__":
    unittest.main()
