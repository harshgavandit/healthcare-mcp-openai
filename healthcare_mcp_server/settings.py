"""Load configuration from the workspace .env regardless of working directory."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=False)


def positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        raise ValueError(f"{name} must be a positive integer") from None
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    model: str
    timeout: int
    max_tokens: int
    max_rounds: int
    host: str
    port: int
    server_url: str

    @classmethod
    def load(cls, require_openai: bool = False):
        key = os.getenv("OPENAI_API_KEY", "").strip()
        if require_openai and (not key or key == "replace-with-your-key"):
            raise ValueError("Set OPENAI_API_KEY in the workspace .env")
        model = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()
        if not model:
            raise ValueError("LLM_MODEL must not be empty")
        host = os.getenv("MCP_HOST", "127.0.0.1").strip()
        port = positive_int("MCP_PORT", 8000)
        if port > 65535:
            raise ValueError("MCP_PORT must be between 1 and 65535")
        return cls(key, model, positive_int("OPENAI_TIMEOUT_SECONDS", 30),
                   positive_int("OPENAI_MAX_COMPLETION_TOKENS", 1200),
                   positive_int("AGENT_MAX_ROUNDS", 8), host, port,
                   os.getenv("MCP_SERVER_URL", f"http://{host}:{port}/mcp").strip())
