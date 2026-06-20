"""Environment-backed configuration."""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


ROOT = Path(__file__).resolve().parents[1]
_load_dotenv(ROOT / ".env")

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'whoop_policy.sqlite3'}")

WHOOP_CLIENT_ID = os.getenv("WHOOP_CLIENT_ID", "")
WHOOP_CLIENT_SECRET = os.getenv("WHOOP_CLIENT_SECRET", "")
WHOOP_REDIRECT_URI = os.getenv("WHOOP_REDIRECT_URI", f"{PUBLIC_BASE_URL}/oauth/whoop/callback")

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))

DEFAULT_RECOVERY_LOW = int(os.getenv("RECOVERY_LOW", "60"))
DEFAULT_RECOVERY_HIGH = int(os.getenv("RECOVERY_HIGH", "80"))
DEFAULT_RECOVERY_CRITICAL = int(os.getenv("RECOVERY_CRITICAL", "30"))
DEFAULT_SLEEP_EFFICIENCY_GOOD = int(os.getenv("SLEEP_EFFICIENCY_GOOD", "85"))
DEFAULT_BUFFER_URGENT_HOURS = float(os.getenv("BUFFER_URGENT_HOURS", "1.5"))
DEFAULT_BUFFER_ANCHORED_HOURS = float(os.getenv("BUFFER_ANCHORED_HOURS", "3.0"))

WHOOP_AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
WHOOP_API_BASE = "https://api.prod.whoop.com/developer"
WHOOP_SCOPE = "offline read:recovery read:sleep read:profile"
