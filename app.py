"""Vercel ASGI entrypoint for the generated-data healthcare demonstration."""
from contextlib import asynccontextmanager, redirect_stdout
import asyncio
import io
import os
from pathlib import Path
import secrets
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
ASK_TIMEOUT_SECONDS = 100
sys.path.insert(0, str(ROOT / "healthcare_mcp_server"))

# This process uses a fresh generated database, never the local patients.db.
import db
from seed_data import seed

DEMO_DIRECTORY = tempfile.TemporaryDirectory(prefix="healthcare-demo-")
db.DB_PATH = str(Path(DEMO_DIRECTORY.name) / "demo.db")
with redirect_stdout(io.StringIO()):
    seed(database_path=db.DB_PATH)

os.environ["MCP_STATELESS_HTTP"] = "1"
hosts = [os.getenv(name, "") for name in ["VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL"]]
os.environ["MCP_ALLOWED_HOSTS"] = ",".join(filter(None, [os.getenv("MCP_ALLOWED_HOSTS", ""), *hosts]))

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from server import mcp, app as mcp_http
from client import run_agent, safe_error
from settings import Settings
from tools.query_tool import query_patient_database
from tools.risk_summary import get_patient_risk_summary
from tools.readmission import get_readmission_insights
from tools.schema_tool import get_database_schema


@asynccontextmanager
async def lifespan(application):
    application.state.ai_slots = asyncio.Semaphore(2)
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Healthcare Explorer", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware("http")
async def response_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/", include_in_schema=False)
async def home():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/health")
async def health():
    settings = Settings.load()
    return {"status": "ok", "data_source": "generated_demo", "model": settings.model,
            "ai_configured": bool(settings.api_key and os.getenv("DEMO_ACCESS_CODE")),
            "mcp_endpoint": "/mcp"}


@app.get("/api/schema")
async def schema():
    return await run_in_threadpool(get_database_schema)


@app.get("/api/patients")
async def patients():
    result = await run_in_threadpool(query_patient_database,
        "SELECT patient_id, name, age, gender, blood_type FROM patients ORDER BY patient_id", 50)
    return {"patients": result["results"], "data_source": "generated_demo"}


@app.get("/api/patients/{patient_id}")
async def patient(patient_id: int):
    risk = await run_in_threadpool(get_patient_risk_summary, patient_id)
    if "error" in risk:
        raise HTTPException(404, "Demo patient not found")
    readmission = await run_in_threadpool(get_readmission_insights, patient_id)
    return {"risk": risk, "readmission": readmission, "data_source": "generated_demo"}


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


async def generate_answer(question, settings):
    # Use the real MCP HTTP protocol in-process; no external self-request is needed.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mcp_http)) as transport:
        async with streamable_http_client("http://localhost/mcp", http_client=transport) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                async with AsyncOpenAI(api_key=settings.api_key, timeout=settings.timeout, max_retries=0) as client:
                    return await run_agent(question, session, client, settings)


@app.post("/api/ask")
async def ask(body: Question, request: Request):
    expected = os.getenv("DEMO_ACCESS_CODE", "")
    supplied = request.headers.get("X-Demo-Access-Code", "")
    if not expected or not secrets.compare_digest(supplied, expected):
        raise HTTPException(401, "Enter the AI access code to ask a question.")
    try:
        settings = Settings.load(require_openai=True)
        async def admitted_answer():
            async with request.app.state.ai_slots:
                return await generate_answer(body.question.strip(), settings)
        result = await asyncio.wait_for(admitted_answer(), timeout=ASK_TIMEOUT_SECONDS)
        return {**result, "data_source": "generated_demo"}
    except asyncio.TimeoutError:
        raise HTTPException(504, "The answer took too long. Please try a shorter question.") from None
    except Exception as error:
        raise HTTPException(502, safe_error(error)) from None


app.mount("/assets", StaticFiles(directory=ROOT / "web"), name="assets")
app.mount("/", mcp_http)
