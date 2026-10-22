import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
        self.assertEqual(self.client.get("/api/study-roadmap").status_code, 401)
        self.assertEqual(self.client.get("/api/study-exercises").status_code, 401)

    def test_study_roadmap_includes_semesters_modules_and_defensive_boundaries(self):
        self.assertEqual(self.register().status_code, 200)
        response = self.client.get("/api/study-roadmap")
        self.assertEqual(response.status_code, 200)
        roadmap = response.json()
        self.assertEqual(len(roadmap["semesters"]), 6)
        self.assertEqual(len(roadmap["technicalModules"]), 5)
        self.assertEqual(len(roadmap["selfStudy"]), 3)
        self.assertNotIn("references", roadmap)
        self.assertNotIn("parallelFoundation", roadmap)

        content = str(roadmap).casefold()
        for topic in (
            "python",
            "linux",
            "windows",
            "redes de computadoras",
            "wpa2",
            "wpa3",
            "wep",
            "iso/iec 27001",
            "bases de datos",
            "respaldo",
            "malware",
            "auditoría",
            "forense",
            "cadena de custodia",
            "respuesta a incidentes",
            "security+",
            "eJPT".casefold(),
            "nmap",
            "metasploit",
            "burp suite",
            "1200",
        ):
            with self.subTest(topic=topic):
                self.assertIn(topic, content)
        for excluded in ("ipn", "cecyt", "cetis", "cecyte", "filosofía", "biología", "macroeconomía"):
            with self.subTest(excluded=excluded):
                self.assertNotIn(excluded, content)
        self.assertTrue(all("subjects" not in semester for semester in roadmap["semesters"]))

    def test_study_exercise_answers_are_hidden_until_server_evaluates_them(self):
        self.assertEqual(self.register().status_code, 200)
        exercises_response = self.client.get("/api/study-exercises")
        self.assertEqual(exercises_response.status_code, 200)
        exercises = exercises_response.json()
        self.assertEqual(len(exercises), 12)
        self.assertEqual({exercise["semester"] for exercise in exercises}, set(range(1, 7)))
        self.assertTrue(all(
            sum(exercise["semester"] == semester for exercise in exercises) == 2
            for semester in range(1, 7)
        ))
        self.assertTrue(all("correctIndex" not in exercise for exercise in exercises))
        self.assertTrue(all("explanation" not in exercise for exercise in exercises))

        exercise = exercises[0]
        correct_index = backend.STUDY_EXERCISES[exercise["id"]]["correctIndex"]
        wrong_index = (correct_index + 1) % len(exercise["options"])
        correct_response = self.client.post(
            f"/api/study-exercises/{exercise['id']}/answer",
            headers={"Origin": ORIGIN},
            json={"answer_index": correct_index},
        )
        self.assertEqual(correct_response.status_code, 200)
        self.assertTrue(correct_response.json()["correct"])
        self.assertIn("explanation", correct_response.json())

        wrong_response = self.client.post(
            f"/api/study-exercises/{exercise['id']}/answer",
            headers={"Origin": ORIGIN},
            json={"answer_index": wrong_index},
        )
        self.assertEqual(wrong_response.status_code, 200)
        self.assertFalse(wrong_response.json()["correct"])

        invalid_response = self.client.post(
            f"/api/study-exercises/{exercise['id']}/answer",
            headers={"Origin": ORIGIN},
            json={"answer_index": 99},
        )
        self.assertEqual(invalid_response.status_code, 422)
        missing_response = self.client.post(
            "/api/study-exercises/not-a-real-exercise/answer",
            headers={"Origin": ORIGIN},
            json={"answer_index": 0},
        )
        self.assertEqual(missing_response.status_code, 404)

    def test_glossary_covers_the_added_cybersecurity_topics(self):
        self.assertEqual(self.register().status_code, 200)
        response = self.client.get("/api/glossary")
        self.assertEqual(response.status_code, 200)
        terms = {item["title"] for item in response.json()}
        self.assertGreaterEqual(len(terms), 60)
        for term in (
            "Hardening",
            "RBAC",
            "Modelo OSI",
            "WPA3",
            "IDS e IPS",
            "SIEM",
            "Consultas parametrizadas",
            "CVE",
            "Cadena de custodia",
            "ISO/IEC 27001",
        ):
            with self.subTest(term=term):
                self.assertIn(term, terms)

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

    def test_live_wifi_scenarios_are_unique_private_and_reward_each_family_once(self):
        self.assertEqual(self.register().status_code, 200)
        headers = {"Origin": ORIGIN}
        progress = self.client.get("/api/progress").json()
        user_id = int(progress["user"]["id"].removeprefix("CG-"))
        variant = backend.WIFI_SCENARIO_VARIANTS[0]

        generated = []
        for _ in range(2):
            with patch("backend.secrets.choice", side_effect=[variant, "la biblioteca del campus"]):
                response = self.client.post("/api/scenarios/live", headers=headers)
            self.assertEqual(response.status_code, 200)
            scenario = response.json()
            self.assertTrue(scenario["liveGenerated"])
            self.assertEqual(scenario["type"], "wifi")
            self.assertEqual(len(scenario["decisions"]), 3)
            self.assertTrue(all(set(option) == {"text"} for option in scenario["decisions"]))
            generated.append(scenario)

        self.assertNotEqual(generated[0]["id"], generated[1]["id"])
        correct_indexes = []
        for scenario in generated:
            stored_scenario = backend.scenario_for_user(user_id, scenario["id"])
            correct_indexes.append(
                next(
                    index
                    for index, decision in enumerate(stored_scenario["decisions"])
                    if decision["safe"]
                )
            )

        first = self.client.post(
            f"/api/scenarios/{generated[0]['id']}/decision",
            headers=headers,
            json={"decision_index": correct_indexes[0]},
        )
        second = self.client.post(
            f"/api/scenarios/{generated[1]['id']}/decision",
            headers=headers,
            json={"decision_index": correct_indexes[1]},
        )
        self.assertEqual(first.json()["score"], 15)
        self.assertEqual(second.json()["score"], 0)
        self.assertTrue(second.json()["practiceOnly"])
        self.assertEqual(second.json()["progress"]["points"], 15)

    def test_ai_variation_uses_model_text_but_keeps_server_owned_answers(self):
        self.assertEqual(self.register().status_code, 200)
        source = backend.SCENARIOS["email-urgency"]
        generated_text = backend.GeneratedScenarioText(
            sender="avisos ficticios de biblioteca",
            subject="Revisión simulada del acceso al campus",
            body="Un mensaje ficticio informa de un problema y te pide actuar con urgencia.",
        )
        with patch(
            "backend.generate_ai_scenario_text",
            new=AsyncMock(return_value=generated_text),
        ) as generate:
            response = self.client.post(
                "/api/scenarios/ai",
                headers={"Origin": ORIGIN},
                json={"scenario_id": source["id"]},
            )

        self.assertEqual(response.status_code, 200)
        scenario = response.json()
        self.assertEqual(scenario["simulationKind"], "ai-generated")
        self.assertEqual(scenario["type"], source["type"])
        self.assertEqual(scenario["subject"], generated_text.subject)
        self.assertEqual(scenario["body"], generated_text.body)
        self.assertTrue(all(set(decision) == {"text"} for decision in scenario["decisions"]))
        generate.assert_awaited_once_with(source)

        stored = backend.scenario_for_user(1, scenario["id"])
        self.assertEqual(stored["decisions"], source["decisions"])
        safe_index = next(
            index for index, decision in enumerate(stored["decisions"]) if decision["safe"]
        )
        result = self.client.post(
            f"/api/scenarios/{scenario['id']}/decision",
            headers={"Origin": ORIGIN},
            json={"decision_index": safe_index},
        )
        self.assertEqual(result.json()["score"], 15)

    def test_ai_variation_requires_authentication_and_known_scenario(self):
        unauthenticated = self.client.post(
            "/api/scenarios/ai",
            headers={"Origin": ORIGIN},
            json={"scenario_id": "email-urgency"},
        )
        self.assertEqual(unauthenticated.status_code, 401)

        self.assertEqual(self.register().status_code, 200)
        unknown = self.client.post(
            "/api/scenarios/ai",
            headers={"Origin": ORIGIN},
            json={"scenario_id": "not-a-scenario"},
        )
        self.assertEqual(unknown.status_code, 404)

    def test_ai_generation_calls_openrouter_with_only_scenario_context(self):
        captured = {}

        class OpenRouterResponse:
            status_code = 200
            is_success = True

            @staticmethod
            def json():
                return {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"sender":"aviso ficticio del campus",'
                                    '"subject":"Aviso de prueba sobre una cuenta",'
                                    '"body":"Un mensaje ficticio te informa de una revisión y pide actuar con urgencia."}'
                                )
                            }
                        }
                    ]
                }

        class OpenRouterClient:
            def __init__(self, timeout):
                captured["timeout"] = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

            async def post(self, url, headers, json):
                captured["url"] = url
                captured["headers"] = headers
                captured["payload"] = json
                return OpenRouterResponse()

        with patch.dict(
            "os.environ",
            {
                "CIBERGUARD_OPENROUTER_API_KEY": "test-api-key",
                "CIBERGUARD_OPENROUTER_MODEL": backend.DEFAULT_AI_MODEL,
            },
        ), patch("backend.httpx.AsyncClient", OpenRouterClient):
            generated = asyncio.run(
                backend.generate_ai_scenario_text(backend.SCENARIOS["email-urgency"])
            )

        self.assertEqual(generated.sender, "aviso ficticio del campus")
        self.assertEqual(captured["url"], backend.OPENROUTER_CHAT_URL)
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-api-key")
        self.assertEqual(captured["payload"]["model"], backend.DEFAULT_AI_MODEL)
        prompt = captured["payload"]["messages"][1]["content"]
        self.assertIn("original_situation", prompt)
        self.assertNotIn(backend.SCENARIOS["email-urgency"]["decisions"][0]["text"], prompt)

    def test_ai_generation_reports_missing_openrouter_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(backend.HTTPException) as error:
                asyncio.run(
                    backend.generate_ai_scenario_text(backend.SCENARIOS["email-urgency"])
                )
        self.assertEqual(error.exception.status_code, 503)

    def test_live_wifi_recovery_reward_counts_toward_family_limit(self):
        self.assertEqual(self.register().status_code, 200)
        headers = {"Origin": ORIGIN}
        variant = backend.WIFI_SCENARIO_VARIANTS[1]

        generated = []
        for _ in range(2):
            with patch("backend.secrets.choice", side_effect=[variant, "la biblioteca del campus"]):
                response = self.client.post("/api/scenarios/live", headers=headers)
            self.assertEqual(response.status_code, 200)
            generated.append(response.json())

        first_scenario = backend.scenario_for_user(1, generated[0]["id"])
        unsafe_index = next(
            index for index, decision in enumerate(first_scenario["decisions"]) if not decision["safe"]
        )
        unsafe = self.client.post(
            f"/api/scenarios/{generated[0]['id']}/decision",
            headers=headers,
            json={"decision_index": unsafe_index},
        )
        self.assertTrue(unsafe.json()["recoveryAvailable"])

        recovered = self.client.post(
            f"/api/scenarios/{generated[0]['id']}/recovery",
            headers=headers,
            json={"safe": True},
        )
        self.assertEqual(recovered.json()["score"], 5)

        second_scenario = backend.scenario_for_user(1, generated[1]["id"])
        safe_index = next(
            index for index, decision in enumerate(second_scenario["decisions"]) if decision["safe"]
        )
        second = self.client.post(
            f"/api/scenarios/{generated[1]['id']}/decision",
            headers=headers,
            json={"decision_index": safe_index},
        )
        self.assertEqual(second.json()["score"], 0)
        self.assertTrue(second.json()["practiceOnly"])
        self.assertEqual(second.json()["progress"]["points"], 5)

    def test_attack_simulations_are_fictional_and_score_defensive_responses(self):
        self.assertEqual(self.register().status_code, 200)
        headers = {"Origin": ORIGIN}
        attack_variants = [
            variant
            for variant in backend.WIFI_SCENARIO_VARIANTS
            if variant.get("kind") == "attack-simulation"
        ]
        self.assertGreaterEqual(len(attack_variants), 3)

        for variant in attack_variants:
            with patch(
                "backend.secrets.choice",
                side_effect=[variant, "la biblioteca del campus"],
            ):
                response = self.client.post("/api/scenarios/live", headers=headers)
            self.assertEqual(response.status_code, 200)
            scenario = response.json()
            self.assertEqual(scenario["simulationKind"], "attack-simulation")
            self.assertIn("ficticio", scenario["category"])
            self.assertTrue(all(set(decision) == {"text"} for decision in scenario["decisions"]))

            stored = backend.scenario_for_user(1, scenario["id"])
            safe_index = next(
                index for index, decision in enumerate(stored["decisions"]) if decision["safe"]
            )
            result = self.client.post(
                f"/api/scenarios/{scenario['id']}/decision",
                headers=headers,
                json={"decision_index": safe_index},
            )
            self.assertTrue(result.json()["safe"])

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
