from contextlib import redirect_stdout, closing
from datetime import date
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db
from client import run_agent, safe_error
from openai.types.chat import ChatCompletion
from settings import Settings
from tools.query_tool import query_patient_database
from tools.readmission import get_readmission_insights
from tools.risk_summary import get_patient_risk_summary


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(db, "DB_PATH", str(Path(self.tmp.name) / "test.db"))
        self.path_patch.start()
        with redirect_stdout(io.StringIO()):
            db.create_tables()
        with closing(db.get_connection()) as conn, conn:
            conn.execute("INSERT INTO patients(patient_id,name,age) VALUES(1,'Example',40)")
            conn.execute("INSERT INTO visits(patient_id,visit_date,discharge_date) VALUES(1,'2026-10-15','2026-10-16')")
            conn.execute("INSERT INTO visits(patient_id,visit_date,discharge_date) VALUES(1,'2026-10-13',NULL)")
            conn.execute("INSERT INTO visits(patient_id,visit_date,discharge_date) VALUES(1,'2026-10-01','2026-10-03')")

    def tearDown(self):
        self.path_patch.stop()
        self.tmp.cleanup()

    def test_bounded_query_and_join(self):
        result = query_patient_database("SELECT p.patient_id FROM patients p JOIN visits v ON p.patient_id=v.patient_id", 2)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["row_count"], 2)

    def test_invalid_limits(self):
        for value in [-1, 0, 501, True, "10"]:
            with self.subTest(value=value):
                self.assertEqual(query_patient_database("SELECT 1", value)["status"], "error")

    def test_writes_and_extension_blocked(self):
        for sql in ["DELETE FROM patients", "SELECT 1; DROP TABLE patients", "SELECT load_extension('x')"]:
            with self.subTest(sql=sql):
                self.assertEqual(query_patient_database(sql)["status"], "error")
        self.assertEqual(query_patient_database("SELECT COUNT(*) AS n FROM patients")["results"][0]["n"], 1)

    def test_expensive_select_interrupted(self):
        sql = "SELECT SUM(x) FROM (WITH RECURSIVE cnt(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM cnt WHERE x<100000000) SELECT x FROM cnt)"
        self.assertEqual(query_patient_database(sql)["status"], "error")

    def test_missing_database_not_created(self):
        missing = Path(self.tmp.name) / "missing.db"
        with patch.object(db, "DB_PATH", str(missing)):
            self.assertEqual(query_patient_database("SELECT 1")["status"], "error")
        self.assertFalse(missing.exists())

    def test_future_visits_and_latest_discharge(self):
        class FixedDate(date):
            @classmethod
            def today(cls):
                return cls(2026, 10, 14)
        with patch("tools.readmission.date", FixedDate):
            result = get_readmission_insights(1)
        self.assertEqual(result["visit_counts"]["last_30_days"], 2)
        self.assertEqual(result["last_discharge_date"], "2026-10-03")
        self.assertEqual(result["days_since_last_discharge"], 11)

    def test_low_risk_and_missing_patient(self):
        self.assertEqual(get_patient_risk_summary(1)["risk_tier"], "LOW")
        self.assertIn("error", get_patient_risk_summary(-1))
        self.assertIn("error", get_readmission_insights(-1))


def completion(content=None, calls=None, reason="stop"):
    return ChatCompletion.model_validate({"id": "test", "object": "chat.completion", "created": 0,
        "model": "gpt-4o-mini", "choices": [{"index": 0, "finish_reason": reason,
        "message": {"role": "assistant", "content": content, "tool_calls": calls}}]})


def call(name="database_schema", arguments="{}"):
    return {"id": "call_1", "type": "function", "function": {"name": name, "arguments": arguments}}


class AgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from mcp.types import ListToolsResult, Tool, CallToolResult, TextContent
        self.settings = Settings("secret-for-test", "gpt-4o-mini", 30, 1200, 3,
                                 "127.0.0.1", 8000, "http://127.0.0.1:8000/mcp")
        self.session = AsyncMock()
        self.session.list_tools.return_value = ListToolsResult(tools=[Tool(
            name="database_schema", inputSchema={"type": "object", "properties": {}}, description="Schema")])
        self.session.call_tool.return_value = CallToolResult(content=[TextContent(type="text", text='{"table_count":5}')])
        self.client = AsyncMock()

    async def test_tool_loop_and_model_configuration(self):
        self.client.chat.completions.create.side_effect = [completion(calls=[call()], reason="tool_calls"),
                                                          completion("Five tables (database_schema).")]
        result = await run_agent("Count tables", self.session, self.client, self.settings)
        self.assertEqual(result["tools_used"], ["database_schema"])
        self.session.call_tool.assert_awaited_once_with("database_schema", {})
        self.assertEqual(self.client.chat.completions.create.call_args.kwargs["model"], "gpt-4o-mini")
        self.assertNotIn("secret-for-test", repr(self.settings))

    async def test_unknown_tool_rejected(self):
        self.client.chat.completions.create.return_value = completion(calls=[call("erase_records")])
        with self.assertRaisesRegex(RuntimeError, "unknown"):
            await run_agent("Test", self.session, self.client, self.settings)
        self.session.call_tool.assert_not_awaited()

    async def test_invalid_arguments_rejected(self):
        self.client.chat.completions.create.return_value = completion(calls=[call(arguments="[]")])
        with self.assertRaisesRegex(RuntimeError, "invalid tool arguments"):
            await run_agent("Test", self.session, self.client, self.settings)

    async def test_truncated_and_empty_answer_rejected(self):
        for response in [completion("partial", reason="length"), completion("")]:
            self.client.chat.completions.create.return_value = response
            with self.assertRaises(RuntimeError):
                await run_agent("Test", self.session, self.client, self.settings)

    async def test_loop_bound(self):
        self.client.chat.completions.create.return_value = completion(calls=[call()], reason="tool_calls")
        with self.assertRaisesRegex(RuntimeError, "AGENT_MAX_ROUNDS"):
            await run_agent("Test", self.session, self.client, self.settings)
        self.assertEqual(self.client.chat.completions.create.await_count, 3)

    def test_invalid_config_and_redacted_unknown_error(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "", "MCP_PORT": "-1"}):
            with self.assertRaises(ValueError):
                Settings.load(require_openai=True)
            with self.assertRaises(ValueError):
                Settings.load()
        self.assertNotIn("private", safe_error(Exception("private")))


if __name__ == "__main__":
    unittest.main()
