"""Repeatable HTTP MCP verification; --live also makes a small OpenAI request."""
import argparse
import asyncio
from dataclasses import replace
import hashlib
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from openai import AsyncOpenAI

from client import run_agent, safe_error
from db import DB_PATH
from settings import Settings, ROOT


def unpack(result):
    assert not result.isError, "MCP tool returned a protocol error"
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(next(item.text for item in result.content if item.type == "text"))


async def verify(settings, live):
    async with streamable_http_client(settings.server_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = sorted(tool.name for tool in (await session.list_tools()).tools)
            assert names == ["database_schema", "patient_risk_summary", "query_database", "readmission_insights"]
            schema = unpack(await session.call_tool("database_schema", {}))
            assert schema["table_count"] == 5
            counts = {name: value["row_count"] for name, value in schema["tables"].items()}
            assert counts["patients"] > 0
            query = unpack(await session.call_tool("query_database", {
                "sql_query": "SELECT patient_id FROM patients ORDER BY patient_id", "max_rows": 2}))
            assert query["status"] == "success" and query["row_count"] == min(2, counts["patients"])
            ids = unpack(await session.call_tool("query_database", {
                "sql_query": "SELECT patient_id FROM patients", "max_rows": 500}))["results"]
            for row in ids:
                pid = row["patient_id"]
                risk = unpack(await session.call_tool("patient_risk_summary", {"patient_id": pid}))
                assert risk["risk_tier"] in {"LOW", "MEDIUM", "HIGH"}
                readmission = unpack(await session.call_tool("readmission_insights", {"patient_id": pid}))
                assert readmission["readmission_risk"] in {"LOW", "MODERATE", "HIGH"}
                windows = readmission["visit_counts"]
                assert windows["last_30_days"] <= windows["last_90_days"] <= windows["last_180_days"]
            for name in ["patient_risk_summary", "readmission_insights"]:
                assert "error" in unpack(await session.call_tool(name, {"patient_id": -1}))
            for sql, limit in [("DELETE FROM patients", 50), ("SELECT 1; DROP TABLE patients", 50),
                               ("SELECT load_extension('untrusted')", 50), ("SELECT 1", -1)]:
                result = unpack(await session.call_tool("query_database", {"sql_query": sql, "max_rows": limit}))
                assert result["status"] == "error"
            report = {"mcp": "passed", "tools": names, "table_counts": counts,
                      "patients_checked": len(ids), "sql_guards": "passed", "openai": "not_requested"}
            if live:
                try:
                    async with AsyncOpenAI(api_key=settings.api_key, timeout=settings.timeout, max_retries=0) as client:
                        result = await run_agent(
                            "Call database_schema and tell me how many tables and patient rows exist. "
                            "Use only schema counts, and do not query any individual patient records.",
                            session, client, settings)
                    assert "database_schema" in result["tools_used"], "Model did not execute MCP tool"
                    report["openai"] = "passed"
                    report["generation"] = result
                except Exception as error:
                    report["openai"] = "failed"
                    report["openai_error"] = safe_error(error)
            return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    settings = Settings.load(require_openai=args.live)
    before = hashlib.sha256(Path(DB_PATH).read_bytes()).hexdigest()
    # Owned temporary server: never stop/reuse a user's existing service.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    settings = replace(settings, host="127.0.0.1", port=port,
                       server_url=f"http://127.0.0.1:{port}/mcp")
    env = {**os.environ, "MCP_HOST": settings.host, "MCP_PORT": str(port)}
    process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("server.py"))],
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 20
        while True:
            if process.poll() is not None:
                raise RuntimeError("Verification server failed to start")
            try:
                with socket.create_connection((settings.host, port), timeout=0.5):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Verification server startup timed out")
                time.sleep(0.2)
        report = asyncio.run(verify(settings, args.live))
        after = hashlib.sha256(Path(DB_PATH).read_bytes()).hexdigest()
        report["database_unchanged"] = before == after
        report["database_sha256"] = after
        assert report["database_unchanged"]
        destination = ROOT / "verification" / ("live.json" if args.live else "local.json")
        destination.parent.mkdir(exist_ok=True)
        destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return int(report["openai"] == "failed")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(safe_error(error), file=sys.stderr)
        raise SystemExit(1)
