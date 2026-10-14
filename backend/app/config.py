"""Runtime configuration and default (admin-editable) detection parameters."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

ENV = os.getenv("INSIDERGUARD_ENV", "development")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'insiderguard.db'}")
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "INSIDERGUARD_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if o.strip()
]
ACCESS_TOKEN_MINUTES = int(os.getenv("INSIDERGUARD_TOKEN_MINUTES", "60"))
JWT_ALGORITHM = "HS256"

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_BATCH_RECORDS = 200_000

# Optional Generative AI API (explanations only; never affects the score).
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_API_URL = os.getenv("AI_API_URL", "https://api.anthropic.com/v1/messages")
AI_MODEL = os.getenv("AI_MODEL", "claude-sonnet-5-5")
AI_TIMEOUT_SECONDS = float(os.getenv("AI_TIMEOUT_SECONDS", "20"))


def _load_secret() -> str:
    env_secret = os.getenv("INSIDERGUARD_SECRET_KEY")
    if env_secret:
        return env_secret
    if ENV == "production":
        raise RuntimeError("INSIDERGUARD_SECRET_KEY must be set in production")
    path = BASE_DIR / ".secret_key"
    if path.exists():
        return path.read_text().strip()
    value = secrets.token_urlsafe(48)
    path.write_text(value)
    os.chmod(path, 0o600)
    return value


SECRET_KEY = _load_secret()

# Default accounts are seeded only outside production, using env overrides if given.
DEFAULT_ADMIN_USER = os.getenv("INSIDERGUARD_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("INSIDERGUARD_ADMIN_PASSWORD", "Guard#12345")
DEFAULT_ANALYST_USER = os.getenv("INSIDERGUARD_ANALYST_USER", "analyst")
DEFAULT_ANALYST_PASSWORD = os.getenv("INSIDERGUARD_ANALYST_PASSWORD", "Review#12345")

# key -> (default value, description). Stored in DB so administrators can modify them (REQ-04-04).
DEFAULT_RULES: dict[str, tuple[float, str]] = {
    # --- rule thresholds ---
    "bulk_download_mb": (500, "Single download size (MB) that triggers the bulk-download rule"),
    "daily_download_mb": (1500, "Total daily download volume (MB) that triggers the bulk-download rule"),
    "failed_logon_count": (5, "Failed logons inside the burst window that trigger the rule"),
    "denied_access_count": (3, "Denied-access events inside the burst window that trigger the rule"),
    "burst_window_min": (10, "Burst window length in minutes"),
    "off_hours_start": (22, "Hour (24h) at/after which activity is off-hours"),
    "off_hours_end": (6, "Hour (24h) before which activity is off-hours"),
    # --- rule / honeytoken weights ---
    "w_bulk_download": (30, "Weight: bulk download (volume category)"),
    "w_failed_logon": (15, "Weight: failed-logon burst (denied category)"),
    "w_denied_access": (20, "Weight: repeated denied access (denied category)"),
    "w_off_hours": (10, "Weight: off-hours activity (time category)"),
    "w_restricted": (15, "Weight: restricted resource access (resource category)"),
    "w_honeytoken": (50, "Weight: honeytoken interaction (highest weight)"),
    # --- anomaly engine ---
    "anomaly_z": (3.0, "Z-score sensitivity above which a deviation raises an anomaly indicator"),
    "baseline_days": (14, "Length of the per-user baseline learning window (days)"),
    "baseline_min_events": (50, "Minimum events in the window before a baseline is established"),
    # --- scoring ---
    "score_window_hours": (8, "Rolling window used when combining indicators into a score"),
    "correlation_window_min": (60, "Window for the correlated-event bonus"),
    "alert_threshold": (30, "Risk score at/above which an alert (incident) is raised"),
    "medium_threshold": (25, "Lower bound of the Medium category"),
    "high_threshold": (50, "Lower bound of the High category"),
    "critical_threshold": (75, "Lower bound of the Critical category"),
    "risk_horizon_days": (7, "Days (back from newest data) used for the 'current' risk score"),
}
