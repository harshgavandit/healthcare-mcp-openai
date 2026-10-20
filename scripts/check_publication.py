"""Scan Git's tracked files without printing any credential values."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = [re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
            re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}"),
            re.compile(rb"github_pat_[A-Za-z0-9_]{20,}")]


def main():
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    names = [name for name in names if name]
    failures = []
    keys = []
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith(("OPENAI_API_KEY=", "DEMO_ACCESS_CODE=")):
                keys.append(line.partition("=")[2].strip().strip("\"'").encode())
    for name in names:
        path = Path(name)
        if (path.name.startswith(".env") and path.name != ".env.example") or path.suffix in {".db", ".sqlite", ".sqlite3"}:
            failures.append((name, "credential or database file"))
        if any(part in {".venv", ".tmp", "__MACOSX", "verification", "__pycache__"} for part in path.parts):
            failures.append((name, "local runtime artifact"))
        data = (ROOT / name).read_bytes()
        if any(key and key in data for key in keys) or any(pattern.search(data) for pattern in PATTERNS):
            failures.append((name, "credential pattern"))
    print(f"Scanned {len(names)} tracked files; detected {len(failures)} publication issues.")
    for name, reason in failures:
        print(f"{name}: {reason}")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
