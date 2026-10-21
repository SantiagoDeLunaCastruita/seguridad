import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import backend


ORIGIN = "http://testserver"


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.original_db_path = backend.DB_PATH
        backend.DB_PATH = Path(self.temp_directory.name) / "test.sqlite3"
        self.client_context = TestClient(backend.app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        backend.DB_PATH = self.original_db_path
        self.temp_directory.cleanup()

    def register(self, email="student@example.edu"):
        return self.client.post(
            "/api/auth/register",
            headers={"Origin": ORIGIN},
            json={
                "email": email,
                "password": "Una clave de práctica 2026!",
                "name": "Estudiante de Prueba",
                "institution": "Universidad de Prueba",
            },
        )

    def test_register_authenticates_and_persists_progress_in_server(self):
        response = self.register()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["set-cookie"].lower().find("httponly") >= 0)

        progress = self.client.get("/api/progress")
        self.assertEqual(progress.status_code, 200)
        self.assertEqual(progress.json()["points"], 0)
        self.assertEqual(progress.json()["user"]["email"], "student@example.edu")

    def test_unauthenticated_users_cannot_access_training_data(self):
        self.assertEqual(self.client.get("/api/scenarios").status_code, 401)
        self.assertEqual(self.client.get("/api/ctf").status_code, 401)

    def test_scenario_answers_and_points_are_server_authoritative(self):
        self.assertEqual(self.register().status_code, 200)
        public_scenarios = self.client.get("/api/scenarios").json()
        first_scenario = public_scenarios[0]
        self.assertNotIn("safe", first_scenario["decisions"][1])
        self.assertNotIn("score", first_scenario["decisions"][1])

        submission = self.client.post(
            f"/api/scenarios/{first_scenario['id']}/decision",
            headers={"Origin": ORIGIN},
            json={"decision_index": 1, "score": 100000},
        )
        self.assertEqual(submission.status_code, 200)
        self.assertEqual(submission.json()["progress"]["points"], 15)

        duplicate = self.client.post(
            f"/api/scenarios/{first_scenario['id']}/decision",
            headers={"Origin": ORIGIN},
            json={"decision_index": 1},
        )
        self.assertTrue(duplicate.json()["alreadyRecorded"])
        self.assertEqual(duplicate.json()["progress"]["points"], 15)

    def test_recovery_branch_updates_risk_and_only_awards_once(self):
        self.assertEqual(self.register().status_code, 200)
        scenario_id = "email-urgency"
        first = self.client.post(
            f"/api/scenarios/{scenario_id}/decision",
            headers={"Origin": ORIGIN},
            json={"decision_index": 0},
        )
        self.assertFalse(first.json()["safe"])
        self.assertTrue(first.json()["recoveryAvailable"])
        self.assertEqual(first.json()["progress"]["points"], 0)

        recovered = self.client.post(
            f"/api/scenarios/{scenario_id}/recovery",
            headers={"Origin": ORIGIN},
            json={"safe": True},
        )
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.json()["progress"]["points"], 5)
        self.assertEqual(recovered.json()["progress"]["vulnerability"], 45)

        repeated = self.client.post(
            f"/api/scenarios/{scenario_id}/recovery",
            headers={"Origin": ORIGIN},
            json={"safe": True},
        )
        self.assertEqual(repeated.status_code, 409)

    def test_ctf_flags_are_not_served_and_solve_rewards_are_idempotent(self):
        self.assertEqual(self.register().status_code, 200)
        challenges = self.client.get("/api/ctf").json()
        self.assertTrue(challenges)
        self.assertNotIn("flag", challenges[0])
        self.assertEqual(self.client.get("/data/scenarios.json").status_code, 404)

        first = self.client.post(
            "/api/ctf/1/submit",
            headers={"Origin": ORIGIN},
            json={"answer": "incorrecta"},
        )
        self.assertFalse(first.json()["correct"])
        correct = self.client.post(
            "/api/ctf/1/submit",
            headers={"Origin": ORIGIN},
            json={"answer": "ciberrevista"},
        )
        self.assertEqual(correct.json()["awarded"], 30)
        repeated = self.client.post(
            "/api/ctf/1/submit",
            headers={"Origin": ORIGIN},
            json={"answer": "ciberrevista"},
        )
        self.assertEqual(repeated.json()["awarded"], 0)
        self.assertEqual(repeated.json()["progress"]["points"], 30)

    def test_mutating_api_requests_require_same_origin(self):
        response = self.client.post(
            "/api/auth/register",
            json={
                "email": "student@example.edu",
                "password": "Una clave de práctica 2026!",
                "name": "Estudiante",
                "institution": "Universidad",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_password_quiz_answer_is_checked_by_server(self):
        self.assertEqual(self.register().status_code, 200)
        options = self.client.get("/api/password-quiz").json()
        self.assertTrue(all("correct" not in option for option in options))

        wrong = self.client.post(
            "/api/password-quiz",
            headers={"Origin": ORIGIN},
            json={"option_id": "seasonal"},
        )
        self.assertFalse(wrong.json()["correct"])
        self.assertEqual(wrong.json()["progress"]["points"], 0)

        right = self.client.post(
            "/api/password-quiz",
            headers={"Origin": ORIGIN},
            json={"option_id": "long-unique"},
        )
        self.assertTrue(right.json()["correct"])
        self.assertEqual(right.json()["progress"]["points"], 10)

    def test_password_lab_reward_is_server_side_and_awarded_once(self):
        self.assertEqual(self.register().status_code, 200)
        first = self.client.post(
            "/api/password-lab/completed",
            headers={"Origin": ORIGIN},
            json={"completed": True},
        )
        self.assertTrue(first.json()["awarded"])
        self.assertEqual(first.json()["progress"]["points"], 5)

        repeated = self.client.post(
            "/api/password-lab/completed",
            headers={"Origin": ORIGIN},
            json={"completed": True},
        )
        self.assertFalse(repeated.json()["awarded"])
        self.assertEqual(repeated.json()["progress"]["points"], 5)

    def test_authenticated_report_and_qr_are_private_no_store(self):
        self.assertEqual(self.register().status_code, 200)
        report = self.client.get("/api/report")
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.headers["cache-control"], "no-store")
        self.assertEqual(report.json()["totalPointsXP"], 0)

        qr = self.client.get("/api/credential/qr")
        self.assertEqual(qr.status_code, 200)
        self.assertEqual(qr.headers["content-type"], "image/svg+xml")
        self.assertIn(b"<svg", qr.content)


if __name__ == "__main__":
    unittest.main()
