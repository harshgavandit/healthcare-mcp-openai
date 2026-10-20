"""Web deployment contracts, using generated demonstration records only."""
import importlib.util
import asyncio
from contextlib import nullcontext
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


class WebDeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if importlib.util.find_spec("app") is not None:
            from starlette.testclient import TestClient
            from app import app
            cls.client = TestClient(app)
            cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "client"):
            cls.client.__exit__(None, None, None)

    def test_browser_and_demo_api_exist(self):
        self.assertIsNotNone(importlib.util.find_spec("app"), "A Vercel ASGI entrypoint is required")
        from starlette.testclient import TestClient
        from app import app
        with nullcontext(self.client) as client:
            home = client.get("/")
            self.assertEqual(home.status_code, 200)
            self.assertIn("Healthcare Explorer", home.text)
            health = client.get("/api/health").json()
            self.assertEqual(health["data_source"], "generated_demo")
            patients = client.get("/api/patients").json()["patients"]
            self.assertEqual(len(patients), 10)
            risk = client.get("/api/patients/4").json()
            self.assertEqual(risk["risk"]["risk_tier"], "HIGH")
            self.assertEqual(client.get("/api/patients/99999").status_code, 404)
            self.assertEqual(client.post("/api/ask", json={"question": "Count tables"}).status_code, 401)
            self.assertEqual(client.post("/api/ask", json={"question": "Count tables"}, headers={"X-Demo-Access-Code": "wrong"}).status_code, 401)

    def test_stateless_mcp_http(self):
        self.assertIsNotNone(importlib.util.find_spec("app"), "A Vercel ASGI entrypoint is required")
        from starlette.testclient import TestClient
        from app import app
        headers = {"Accept": "application/json, text/event-stream"}
        with nullcontext(self.client) as client:
            response = client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-03-26", "capabilities": {},
                    "clientInfo": {"name": "web-test", "version": "1"}}})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("mcp-session-id", response.headers)
            listing = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            self.assertEqual(len(listing.json()["result"]["tools"]), 4)


class QueueTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_queued_question_has_a_bounded_wait(self):
        import app as web_app
        from fastapi import HTTPException
        from starlette.requests import Request
        request = Request({"type": "http", "headers": [(b"x-demo-access-code", b"test-code")],
                           "app": SimpleNamespace(state=SimpleNamespace(ai_slots=asyncio.Semaphore(0)))})
        with patch.dict("os.environ", {"DEMO_ACCESS_CODE": "test-code", "OPENAI_API_KEY": "test-key"}), \
             patch.object(web_app, "ASK_TIMEOUT_SECONDS", 0.02, create=True):
            with self.assertRaises(HTTPException) as result:
                await asyncio.wait_for(web_app.ask(web_app.Question(question="Count tables"), request), timeout=0.2)
        self.assertEqual(result.exception.status_code, 504)


if __name__ == "__main__":
    unittest.main()
