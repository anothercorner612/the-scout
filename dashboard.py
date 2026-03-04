import streamlit as st
import pandas as pd
import sqlite3
import os
import json
import hashlib
from html import escape as _esc
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from scout import run_pipeline

load_dotenv(Path(__file__).parent / ".env")

DB_PATH = Path(__file__).parent / "job_tracker.db"
PROJECT_DIR = Path(__file__).parent
STATUSES = ["Unexplored", "Researched", "Applied", "Followed-Up"]

# --- Inline SVG illustrations as base64 img tags (Streamlit strips raw SVGs) ---
import base64 as _b64

def _svg_img(svg: str, width: int = None) -> str:
    """Convert SVG string to an <img> tag with base64 data URI."""
    encoded = _b64.b64encode(svg.encode()).decode()
    w = f' width="{width}"' if width else ''
    return f'<img src="data:image/svg+xml;base64,{encoded}"{w} alt="">'

_SVG_BINOCULARS = """<svg width="80" height="80" viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="26" cy="48" r="16" stroke="#C4653A" stroke-width="2" fill="none"/>
  <circle cx="54" cy="48" r="16" stroke="#C4653A" stroke-width="2" fill="none"/>
  <path d="M34 20 L26 32" stroke="#C4653A" stroke-width="2" stroke-linecap="round"/>
  <path d="M46 20 L54 32" stroke="#C4653A" stroke-width="2" stroke-linecap="round"/>
  <path d="M34 20 H46" stroke="#C4653A" stroke-width="2" stroke-linecap="round"/>
  <circle cx="26" cy="48" r="6" stroke="#E0D9CF" stroke-width="1.5" fill="none"/>
  <circle cx="54" cy="48" r="6" stroke="#E0D9CF" stroke-width="1.5" fill="none"/>
</svg>"""

_SVG_COMPASS = """<svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="32" cy="32" r="28" stroke="#C4653A" stroke-width="1.5" fill="none"/>
  <circle cx="32" cy="32" r="24" stroke="#E0D9CF" stroke-width="1" fill="none"/>
  <polygon points="32,12 35,30 32,34 29,30" fill="#C4653A" opacity="0.9"/>
  <polygon points="32,52 29,34 32,30 35,34" fill="#E0D9CF"/>
  <circle cx="32" cy="32" r="2.5" fill="#C4653A"/>
  <text x="32" y="9" text-anchor="middle" font-family="DM Sans" font-size="6" fill="#9C9488" font-weight="500">N</text>
</svg>"""

SVG_BINOCULARS = _svg_img(_SVG_BINOCULARS, 80)
SVG_COMPASS = _svg_img(_SVG_COMPASS, 64)

SUBTITLE_ANIMATED = (
    '<div class="scout-subtitle">'
    'Your '
    '<span class="role-spinner"><span class="role-spinner-inner">'
    '<span>dream role</span>'
    '<span>next chapter</span>'
    '<span>career move</span>'
    '<span>perfect fit</span>'
    '<span>big break</span>'
    '<span>next adventure</span>'
    '</span></span>'
    ' job hunter'
    '</div>'
)

SUBTITLE_STATIC = '<div class="scout-subtitle-static">Your job hunter</div>'

TILDE_DIVIDER = '<div class="tilde-divider">~ ~ ~</div>'

_SVG_MAP = """<svg width="72" height="72" viewBox="0 0 72 72" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M12 18 L28 12 L44 18 L60 12 V54 L44 60 L28 54 L12 60 Z" stroke="#C4653A" stroke-width="1.5" fill="none"/>
  <line x1="28" y1="12" x2="28" y2="54" stroke="#E0D9CF" stroke-width="1"/>
  <line x1="44" y1="18" x2="44" y2="60" stroke="#E0D9CF" stroke-width="1"/>
  <circle cx="36" cy="32" r="4" stroke="#C4653A" stroke-width="1.5" fill="none"/>
  <circle cx="36" cy="32" r="1.5" fill="#C4653A"/>
  <path d="M20 28 Q24 24 28 28" stroke="#9C9488" stroke-width="0.8" fill="none"/>
  <path d="M44 40 Q50 36 56 40" stroke="#9C9488" stroke-width="0.8" fill="none"/>
</svg>"""
SVG_MAP = _svg_img(_SVG_MAP, 72)

# --- Gemini client ---
# Support Streamlit Cloud secrets or .env
_gemini_key = os.getenv("gemini_key")
if not _gemini_key:
    try:
        _gemini_key = st.secrets.get("gemini_key")
    except Exception:
        pass
ai_client = genai.Client(api_key=_gemini_key)

# --- Database: Turso (cloud) or local SQLite ---
_turso_url = os.getenv("TURSO_URL")
_turso_token = os.getenv("TURSO_AUTH_TOKEN")
if not _turso_url:
    try:
        _turso_url = st.secrets.get("TURSO_URL")
        _turso_token = st.secrets.get("TURSO_AUTH_TOKEN")
    except Exception:
        pass
USE_TURSO = bool(_turso_url and _turso_token)

st.set_page_config(page_title="The Scout", page_icon="~", layout="wide")

# --- Custom CSS: doodle modern aesthetic ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;1,9..40,300;1,9..40,400&display=swap');

    /* Global type */
    html, body, [class*="css"] {
        font-family: 'DM Sans', sans-serif;
        color: #2D2A26;
    }

    /* Hero title */
    .scout-title {
        font-family: 'Instrument Serif', serif;
        font-size: 3.8rem;
        font-weight: 400;
        letter-spacing: -0.03em;
        line-height: 1.05;
        color: #2D2A26;
        margin-bottom: 0;
        padding-bottom: 0;
        text-align: center;
    }
    .scout-title em {
        font-style: italic;
        color: #C4653A;
    }
    .scout-subtitle {
        font-family: 'DM Sans', sans-serif;
        font-size: 0.85rem;
        font-weight: 300;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #9C9488;
        margin-top: 4px;
        margin-bottom: 2rem;
        text-align: center;
        height: 1.2em;
        line-height: 1.2em;
    }
    .scout-subtitle-static {
        font-family: 'DM Sans', sans-serif;
        font-size: 0.85rem;
        font-weight: 300;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #9C9488;
        margin-top: 4px;
        margin-bottom: 2rem;
    }
    .role-spinner {
        display: inline-block;
        height: 1.2em;
        overflow: hidden;
        vertical-align: top;
    }
    .role-spinner-inner {
        display: flex;
        flex-direction: column;
        animation: role-spin 10s ease-in-out infinite;
    }
    .role-spinner-inner span {
        display: block;
        height: 1.2em;
        line-height: 1.2em;
        color: #C4653A;
        font-weight: 400;
        white-space: nowrap;
    }
    @keyframes role-spin {
        0%, 12%   { transform: translateY(0); }
        16%, 28%  { transform: translateY(-1.2em); }
        32%, 44%  { transform: translateY(-2.4em); }
        48%, 60%  { transform: translateY(-3.6em); }
        64%, 76%  { transform: translateY(-4.8em); }
        80%, 92%  { transform: translateY(-6.0em); }
        96%, 100% { transform: translateY(0); }
    }

    /* Metric cards */
    [data-testid="stMetric"] {
        background: #FFFFFF;
        border: 1.5px solid #E0D9CF;
        border-radius: 2px;
        padding: 1rem 1.2rem;
    }
    [data-testid="stMetricLabel"] {
        font-family: 'DM Sans', sans-serif;
        font-size: 0.72rem !important;
        font-weight: 400;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: #9C9488 !important;
    }
    [data-testid="stMetricValue"] {
        font-family: 'Instrument Serif', serif;
        font-size: 2.2rem !important;
        font-weight: 400;
        color: #2D2A26 !important;
    }

    /* Section headers */
    .section-header {
        font-family: 'Instrument Serif', serif;
        font-size: 1.8rem;
        font-weight: 400;
        color: #2D2A26;
        margin-top: 2rem;
        margin-bottom: 0.3rem;
        border-bottom: 1.5px solid #2D2A26;
        padding-bottom: 0.4rem;
    }
    .section-header::before {
        content: '~ ';
        color: #C4653A;
        font-style: italic;
    }
    .section-hint {
        font-family: 'DM Sans', sans-serif;
        font-size: 0.78rem;
        color: #9C9488;
        font-weight: 300;
        margin-bottom: 1.2rem;
    }

    /* Job cards */
    .job-card {
        background: #FFFFFF;
        border: 1.5px solid #E0D9CF;
        border-radius: 2px;
        padding: 1.5rem 1.8rem;
        margin-bottom: 1rem;
        transition: border-color 0.2s;
    }
    .job-card:hover {
        border-color: #C4653A;
    }
    .job-card-title {
        font-family: 'Instrument Serif', serif;
        font-size: 1.3rem;
        font-weight: 400;
        color: #2D2A26;
        margin-bottom: 0.2rem;
        line-height: 1.2;
    }
    .job-card-company {
        font-family: 'DM Sans', sans-serif;
        font-size: 0.95rem;
        color: #C4653A;
        font-weight: 500;
        margin-bottom: 0.5rem;
    }
    .job-card-meta {
        font-family: 'DM Sans', sans-serif;
        font-size: 0.75rem;
        color: #9C9488;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        font-weight: 400;
    }
    .job-card-detail {
        font-family: 'DM Sans', sans-serif;
        font-size: 0.88rem;
        color: #5A554E;
        line-height: 1.5;
        margin-top: 0.6rem;
    }
    .job-card-link {
        font-family: 'DM Sans', sans-serif;
        font-size: 0.82rem;
        color: #C4653A;
        text-decoration: none;
        font-weight: 500;
    }

    /* Score badge */
    .score-badge {
        display: inline-block;
        font-family: 'Instrument Serif', serif;
        font-size: 1.1rem;
        color: #C4653A;
        border: 1.5px solid #C4653A;
        border-radius: 50%;
        width: 2.4rem;
        height: 2.4rem;
        line-height: 2.2rem;
        text-align: center;
    }

    /* Run info bar */
    .run-info {
        font-family: 'DM Sans', sans-serif;
        font-size: 0.78rem;
        color: #9C9488;
        font-weight: 300;
        letter-spacing: 0.02em;
        padding: 0.8rem 0;
        line-height: 2;
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background: #EFEBE4;
        border-right: 1.5px solid #E0D9CF;
    }
    [data-testid="stSidebar"] .stMarkdown h2 {
        font-family: 'Instrument Serif', serif;
        font-weight: 400;
    }

    /* Hide Streamlit branding but keep sidebar toggle accessible */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    [data-testid="stStatusWidget"] {display: none;}

    /* Expander styling */
    .streamlit-expanderHeader {
        font-family: 'DM Sans', sans-serif;
        font-size: 0.85rem;
        font-weight: 500;
        color: #5A554E;
    }

    /* Table styling */
    .stDataFrame {
        border: 1.5px solid #E0D9CF;
        border-radius: 2px;
    }

    /* Dividers */
    hr {
        border: none;
        border-top: 1px solid #E0D9CF;
    }

    /* Decorative tilde divider */
    .tilde-divider {
        text-align: center;
        color: #E0D9CF;
        font-family: 'Instrument Serif', serif;
        font-size: 1.4rem;
        letter-spacing: 0.5em;
        padding: 0.8rem 0;
        user-select: none;
    }

    /* Greeting */
    .greeting {
        font-family: 'Instrument Serif', serif;
        font-size: 1.1rem;
        font-style: italic;
        color: #9C9488;
        text-align: center;
        margin-bottom: 1rem;
    }

    /* Scout again button */
    .scout-btn {
        display: flex;
        justify-content: flex-end;
        align-items: center;
    }
    .scout-btn > div > button,
    .scout-btn button {
        font-family: 'DM Sans', sans-serif !important;
        font-size: 0.78rem !important;
        font-weight: 500 !important;
        letter-spacing: 0.08em !important;
        text-transform: uppercase !important;
        color: #C4653A !important;
        background: transparent !important;
        border: 1.5px solid #C4653A !important;
        border-radius: 2px !important;
        padding: 0.45rem 1.2rem !important;
        transition: all 0.2s !important;
    }
    .scout-btn > div > button:hover,
    .scout-btn button:hover {
        background: #C4653A !important;
        color: #F7F3ED !important;
    }
    .scout-btn > div > button:active, .scout-btn > div > button:focus,
    .scout-btn button:active, .scout-btn button:focus {
        background: #A8522E !important;
        color: #F7F3ED !important;
        border-color: #A8522E !important;
    }

    /* Running state */
    .scout-running {
        font-family: 'DM Sans', sans-serif;
        font-size: 0.82rem;
        color: #C4653A;
        font-weight: 400;
        padding: 0.5rem 0;
    }
    .scout-done {
        font-family: 'DM Sans', sans-serif;
        font-size: 0.82rem;
        color: #8B9E82;
        font-weight: 400;
        padding: 0.5rem 0;
    }

    /* Network match badge */
    .network-badge {
        display: inline-block;
        font-family: 'DM Sans', sans-serif;
        font-size: 0.72rem;
        font-weight: 500;
        letter-spacing: 0.04em;
        color: #5A7A52;
        background: #E8F0E5;
        border: 1px solid #C5D9BF;
        border-radius: 2px;
        padding: 0.15rem 0.5rem;
        margin-left: 0.5rem;
        vertical-align: middle;
    }

    /* Onboarding */
    .onboard-title {
        font-family: 'Instrument Serif', serif;
        font-size: 2rem;
        font-weight: 400;
        color: #2D2A26;
        margin-bottom: 0.3rem;
    }

    /* Empty state */
    .empty-state {
        text-align: center;
        padding: 4rem 2rem 3rem;
    }
    .empty-state svg {
        margin-bottom: 1.5rem;
        opacity: 0.85;
    }
    .empty-state-heading {
        font-family: 'Instrument Serif', serif;
        font-size: 1.6rem;
        color: #2D2A26;
        margin-bottom: 0.5rem;
    }
    .empty-state-body {
        font-family: 'DM Sans', sans-serif;
        font-size: 0.88rem;
        color: #9C9488;
        font-weight: 300;
        max-width: 420px;
        margin: 0 auto 1.5rem;
        line-height: 1.5;
    }

    /* Setup header illustration */
    .setup-illustration {
        text-align: center;
        margin-bottom: 0.5rem;
    }
    .setup-illustration svg {
        opacity: 0.8;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# DATABASE CONNECTION + SCHEMA
# ============================================================

class TursoConnection:
    """Talk to Turso via its HTTP pipeline API using httpx. No WebSocket needed."""

    def __init__(self, url, auth_token):
        import httpx as _httpx
        self._base = url.replace("libsql://", "https://")
        self._token = auth_token
        self._http = _httpx.Client(timeout=30.0)

    def execute(self, sql, params=None):
        args = list(params) if params else []
        # Build Turso v2 pipeline request
        stmt = {"sql": sql}
        if args:
            stmt["args"] = [_turso_val(a) for a in args]
        body = {"requests": [
            {"type": "execute", "stmt": stmt},
            {"type": "close"},
        ]}
        resp = self._http.post(
            f"{self._base}/v2/pipeline",
            json=body,
            headers={"Authorization": f"Bearer {self._token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        result = data.get("results", [{}])[0].get("response", {}).get("result", {})
        cols = [c.get("name", "") for c in result.get("cols", [])]
        rows = []
        for row in result.get("rows", []):
            rows.append(tuple(_from_turso_val(v) for v in row))
        return TursoCursor(cols, rows)

    def commit(self):
        pass  # auto-commit

    def close(self):
        self._http.close()


def _turso_val(v):
    """Convert a Python value to Turso API value format."""
    if v is None:
        return {"type": "null", "value": None}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    return {"type": "text", "value": str(v)}


def _from_turso_val(v):
    """Convert a Turso API value back to Python."""
    if v is None or v.get("type") == "null":
        return None
    val = v.get("value")
    if v.get("type") == "integer":
        return int(val)
    if v.get("type") == "float":
        return float(val)
    return val


class TursoCursor:
    """Mimics sqlite3 cursor from Turso HTTP API results."""

    def __init__(self, columns, rows):
        self._columns = columns
        self._rows = rows

    @property
    def description(self):
        return [(col, None, None, None, None, None, None) for col in self._columns]

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


@st.cache_resource
def get_connection():
    if USE_TURSO:
        return TursoConnection(_turso_url, _turso_token)
    return sqlite3.connect(str(DB_PATH), check_same_thread=False)


def query_df(sql, params=None):
    """Run a query and return a DataFrame. Works with both sqlite3 and Turso."""
    conn = get_connection()
    if USE_TURSO:
        cursor = conn.execute(sql, params or ())
        if cursor._columns:
            return pd.DataFrame(cursor.fetchall(), columns=cursor._columns)
        return pd.DataFrame()
    return pd.read_sql(sql, conn, params=params)


def ensure_schema():
    """Create/migrate all tables."""
    conn = get_connection()

    # Core jobs table (shared pool)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            url                   TEXT UNIQUE,
            title                 TEXT,
            company               TEXT,
            platform              TEXT,
            description           TEXT,
            posted_at             DATETIME,
            hiring_manager_name   TEXT,
            hiring_manager_title  TEXT,
            company_win           TEXT,
            salary_min            INTEGER,
            salary_max            INTEGER,
            salary_source         TEXT,
            glassdoor_rating      TEXT,
            culture_flags         TEXT,
            discovered_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at            DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Run log
    conn.execute("""
        CREATE TABLE IF NOT EXISTS run_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            finished_at DATETIME,
            jobs_found INTEGER DEFAULT 0,
            jobs_scored INTEGER DEFAULT 0,
            jobs_enriched INTEGER DEFAULT 0
        )
    """)

    # Users table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username        TEXT UNIQUE NOT NULL,
            name            TEXT,
            email           TEXT,
            password_hash   TEXT NOT NULL,
            resume_json     TEXT,
            goals_text      TEXT,
            scoring_prompt  TEXT,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Per-user job overlay
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_jobs (
            user_id         INTEGER NOT NULL,
            job_id          INTEGER NOT NULL,
            score           INTEGER,
            tier            TEXT,
            score_reasoning TEXT,
            status          TEXT DEFAULT 'Unexplored',
            cover_letter    TEXT,
            resume_tips     TEXT,
            similar_roles   TEXT,
            culture_notes   TEXT,
            vibe_check_email TEXT,
            PRIMARY KEY (user_id, job_id)
        )
    """)

    # Contacts table for LinkedIn networking map
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER,
            first_name    TEXT,
            last_name     TEXT,
            email         TEXT,
            company       TEXT,
            position      TEXT,
            connected_on  TEXT
        )
    """)

    # Migrate legacy jobs table — add missing columns from older schema
    existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    legacy_cols = {
        "score": "INTEGER", "tier": "TEXT", "status": "TEXT",
        "score_reasoning": "TEXT", "vibe_check_email": "TEXT",
        "cover_letter": "TEXT", "resume_tips": "TEXT",
        "similar_roles": "TEXT", "culture_notes": "TEXT",
        "posted_at": "DATETIME", "salary_min": "INTEGER",
        "salary_max": "INTEGER", "salary_source": "TEXT",
        "glassdoor_rating": "TEXT", "culture_flags": "TEXT",
        "hiring_manager_name": "TEXT", "hiring_manager_title": "TEXT",
        "company_win": "TEXT",
    }
    for col, col_type in legacy_cols.items():
        if col not in existing:
            try:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {col_type}")
            except Exception:
                pass

    # Add user_id to contacts if missing
    contacts_cols = {row[1] for row in conn.execute("PRAGMA table_info(contacts)").fetchall()}
    if "user_id" not in contacts_cols:
        try:
            conn.execute("ALTER TABLE contacts ADD COLUMN user_id INTEGER")
        except Exception:
            pass

    # Add api_calls and user_id to run_log if missing
    run_log_cols = {row[1] for row in conn.execute("PRAGMA table_info(run_log)").fetchall()}
    for col, col_type in [("api_calls", "INTEGER DEFAULT 0"), ("user_id", "INTEGER")]:
        if col not in run_log_cols:
            try:
                conn.execute(f"ALTER TABLE run_log ADD COLUMN {col} {col_type}")
            except Exception:
                pass

    conn.commit()


ensure_schema()


# ============================================================
# SESSION COOKIE HELPERS (persistent login across app restarts)
# ============================================================

import hmac as _hmac
import time as _time
import streamlit.components.v1 as _components

_SESSION_SECRET = os.getenv("SESSION_SECRET", "the-scout-2026-session-key")
_SESSION_COOKIE = "scout_session"
_SESSION_MAX_AGE_DAYS = 30


def _make_session_token(user_id: int) -> str:
    """Create an HMAC-signed session token: user_id:timestamp:signature."""
    payload = f"{user_id}:{int(_time.time())}"
    sig = _hmac.new(_SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{payload}:{sig}"


def _verify_session_token(token: str):
    """Verify token and return user_id, or None if invalid/expired."""
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return None
        user_id, ts, sig = int(parts[0]), int(parts[1]), parts[2]
        expected = _hmac.new(
            _SESSION_SECRET.encode(), f"{user_id}:{ts}".encode(), hashlib.sha256
        ).hexdigest()[:16]
        if not _hmac.compare_digest(sig, expected):
            return None
        if _time.time() - ts > _SESSION_MAX_AGE_DAYS * 86400:
            return None
        return user_id
    except (ValueError, TypeError):
        return None


def _set_session_cookie(user_id: int):
    """Inject JS to set a persistent session cookie."""
    token = _make_session_token(user_id)
    max_age = _SESSION_MAX_AGE_DAYS * 86400
    _components.html(
        f'<script>document.cookie="{_SESSION_COOKIE}={token}; path=/; max-age={max_age}; SameSite=Lax";</script>',
        height=0,
    )


def _clear_session_cookie():
    """Inject JS to delete the session cookie."""
    _components.html(
        f'<script>document.cookie="{_SESSION_COOKIE}=; path=/; max-age=0; SameSite=Lax";</script>',
        height=0,
    )


def _get_cookie_user_id():
    """Try to read and verify the session cookie. Returns user_id or None."""
    try:
        cookies = st.context.cookies
        token = cookies.get(_SESSION_COOKIE)
        if token:
            return _verify_session_token(token)
    except Exception:
        pass
    return None


# ============================================================
# AUTH HELPERS (simple hash-based, upgraded to bcrypt in Phase 5)
# ============================================================

def _hash_password(password: str) -> str:
    import bcrypt
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _check_password(password: str, password_hash: str) -> bool:
    import bcrypt
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except (ValueError, TypeError):
        # Fallback for legacy SHA-256 hashes (pre-bcrypt migration)
        return hashlib.sha256(password.encode()).hexdigest() == password_hash


def reset_password(username: str, email: str, new_password: str) -> bool:
    """Reset password if username + email match."""
    conn = get_connection()
    row = conn.execute(
        "SELECT id, email FROM users WHERE username = ?",
        (username.lower().strip(),),
    ).fetchone()
    if not row:
        return False
    stored_email = row[1] or ""
    if stored_email.lower().strip() != email.lower().strip():
        return False
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (_hash_password(new_password), row[0]),
    )
    conn.commit()
    return True


def register_user(username: str, password: str, name: str, email: str) -> bool:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, name, email) VALUES (?, ?, ?, ?)",
            (username.lower().strip(), _hash_password(password), name, email),
        )
        conn.commit()
        return True
    except Exception:
        return False


def login_user(username: str, password: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM users WHERE username = ?",
        (username.lower().strip(),),
    ).fetchone()
    if row:
        cols = [d[0] for d in conn.execute("SELECT * FROM users WHERE 1=0").description]
        user = dict(zip(cols, row))
        if _check_password(password, user["password_hash"]):
            user.pop("password_hash", None)
            return user
    return None


def get_user(user_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row:
        cols = [d[0] for d in conn.execute("SELECT * FROM users WHERE 1=0").description]
        user = dict(zip(cols, row))
        user.pop("password_hash", None)
        return user
    return None


_ALLOWED_USER_FIELDS = {"resume_json", "goals_text", "scoring_prompt", "name", "email"}

def update_user_field(user_id: int, field: str, value):
    if field not in _ALLOWED_USER_FIELDS:
        raise ValueError(f"Field not allowed: {field}")
    conn = get_connection()
    conn.execute(f"UPDATE users SET {field} = ? WHERE id = ?", (value, user_id))
    conn.commit()


# ============================================================
# PDF RESUME PARSING
# ============================================================

def parse_resume_pdf(pdf_bytes: bytes) -> dict:
    """Upload PDF to Gemini Flash, get structured resume back."""
    response = ai_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            {
                "role": "user",
                "parts": [
                    {"inline_data": {"mime_type": "application/pdf", "data": __import__("base64").b64encode(pdf_bytes).decode()}},
                    {"text": """Extract structured data from this resume PDF. Return ONLY valid JSON with this exact structure:
{
  "summary": "<2-3 sentence professional summary>",
  "skills": "<comma-separated list of key skills>",
  "bullets": {
    "Role Title, Company (dates)": ["bullet point 1", "bullet point 2", ...],
    ...
  }
}

Include ALL roles with their bullet points. Keep bullet text concise but preserve numbers and specifics."""},
                ],
            }
        ],
        config={"temperature": 0.1},
    )
    return _extract_json(response.text) or {}


def generate_scoring_prompt(resume_json: dict, goals_text: str) -> str:
    """Use Gemini to generate a personalized scoring system prompt from resume + goals."""
    resume_str = json.dumps(resume_json, indent=2)[:3000]
    response = ai_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"""Given this candidate's resume and job search goals, generate a STRICT scoring system prompt for evaluating job fit (0-100 scale).

RESUME:
{resume_str}

GOALS:
{goals_text or "Not specified — generate a general-purpose scoring prompt based on the resume"}

IMPORTANT — THE PROMPT YOU GENERATE MUST ENFORCE THESE CALIBRATION RULES:

1. SCORE DISTRIBUTION: Most jobs should land in the 45-75 range. Scores above 85 should be uncommon (fewer than 15% of jobs). A score of 100 should almost never be given — it means the role is a once-in-a-year perfect match. Importantly, any legitimate role in the candidate's general field should score at LEAST 45-55 even if it isn't a strong fit.

2. SCORING RANGES the prompt must define:
   - 90-100: EXCEPTIONAL — Near-perfect match on role function, seniority, industry, AND 3+ differentiating skills. Uncommon.
   - 80-89 (tier1): STRONG — Core daily responsibilities clearly match the candidate's primary expertise.
   - 65-79 (tier2): SOLID — Good company, reasonable role, but missing 1-2 key alignment factors (wrong specialization, adjacent function, etc.)
   - 45-64: MEDIOCRE — Right industry but wrong specialization, or right function but wrong industry. Most generic roles in the candidate's field land here.
   - 25-44: WEAK — Tangential connection at best.
   - 0-24: HARD REJECT — Wrong function entirely, spam, or major red flags.

3. BONUS KEYWORDS: Pick 8-12 keywords that are truly DIFFERENTIATING for this candidate — skills/tools that set them apart from other candidates in their field, NOT table stakes. Generic industry-standard terms that appear in most postings of this type MUST NOT be bonus keywords. Each bonus is +3 (not +5), and TOTAL BONUS IS CAPPED AT +10.

4. PENALTIES the prompt must include:
   - If the role's PRIMARY function is marketing, legal, finance, HR, sales, or support → subtract 15 (even if title says "Operations Manager" or "Program Manager")
   - If the title implies a seniority mismatch (too senior or too junior) → subtract 10
   - If the posting requires a language the candidate doesn't speak → score 0
   - If the posting is region-locked outside the candidate's location → score 0

5. CALIBRATION EXAMPLES the prompt must include (adapted to this candidate):
   - "A score of 50 looks like: [example of a mediocre-fit role for THIS candidate]"
   - "A score of 75 looks like: [example of a solid-fit role for THIS candidate]"
   - "A score of 90 looks like: [example of an exceptional role for THIS candidate]"

Generate the prompt with these sections:
- Candidate summary (2-3 sentences)
- Tier 1 definition (base 76-88)
- Tier 2 definition (base 60-75)
- No Match definition (base 40-55)
- Differentiating bonus keywords (8-12 terms, +3 each, cap +10 total)
- Penalties (role mismatch, seniority mismatch, etc.)
- Hard rejects (score=0)
- Calibration examples (what 50, 75, 90 look like for this person)
- End with: Return ONLY a JSON array: [{{"id":<job_id>,"score":<0-100>,"tier":"tier1"|"tier2"|"no_match","reasoning":"<1 sentence>"}}]

Return ONLY the scoring system prompt text, nothing else.""",
        config={"temperature": 0.3},
    )
    return response.text.strip()


# ============================================================
# PER-USER DATA HELPERS
# ============================================================

def load_jobs_for_user(user_id: int):
    """Load jobs with per-user overlay (score, status, materials from user_jobs)."""
    return query_df("""
        SELECT j.id, j.url, j.title, j.company, j.platform, j.description,
            j.posted_at, j.hiring_manager_name, j.hiring_manager_title,
            j.company_win, j.salary_min, j.salary_max, j.salary_source,
            j.glassdoor_rating, j.culture_flags, j.discovered_at, j.updated_at,
            COALESCE(uj.score, j.score) as score,
            COALESCE(uj.tier, j.tier) as tier,
            COALESCE(uj.score_reasoning, j.score_reasoning) as score_reasoning,
            COALESCE(uj.status, j.status, 'Unexplored') as status,
            COALESCE(uj.cover_letter, j.cover_letter) as cover_letter,
            COALESCE(uj.resume_tips, j.resume_tips) as resume_tips,
            COALESCE(uj.similar_roles, j.similar_roles) as similar_roles,
            COALESCE(uj.culture_notes, j.culture_notes) as culture_notes,
            COALESCE(uj.vibe_check_email, j.vibe_check_email) as vibe_check_email
        FROM jobs j
        LEFT JOIN user_jobs uj ON uj.job_id = j.id AND uj.user_id = ?
        ORDER BY COALESCE(uj.score, j.score) DESC
    """, params=(user_id,))


def load_jobs_legacy():
    """Load jobs for legacy (no user) mode."""
    return query_df("SELECT * FROM jobs ORDER BY score DESC")


def update_user_job_status(user_id: int, job_id: int, new_status: str):
    conn = get_connection()
    conn.execute("""
        INSERT INTO user_jobs (user_id, job_id, status) VALUES (?, ?, ?)
        ON CONFLICT (user_id, job_id) DO UPDATE SET status = ?
    """, (user_id, job_id, new_status, new_status))
    conn.commit()


def save_user_materials(user_id: int, job_id: int, materials: dict):
    conn = get_connection()
    conn.execute("""
        INSERT INTO user_jobs (user_id, job_id, cover_letter, resume_tips, similar_roles, culture_notes)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (user_id, job_id) DO UPDATE SET
            cover_letter = ?, resume_tips = ?, similar_roles = ?, culture_notes = ?
    """, (
        user_id, job_id,
        _to_str(materials.get("cover_letter")),
        _to_str(materials.get("resume_tips")),
        _to_str(materials.get("similar_roles")),
        _to_str(materials.get("culture_notes")),
        _to_str(materials.get("cover_letter")),
        _to_str(materials.get("resume_tips")),
        _to_str(materials.get("similar_roles")),
        _to_str(materials.get("culture_notes")),
    ))
    conn.commit()


def load_last_run(user_id=None):
    try:
        if user_id:
            df = query_df(
                "SELECT * FROM run_log WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                params=(user_id,),
            )
        else:
            df = query_df("SELECT * FROM run_log ORDER BY id DESC LIMIT 1")
        return df.to_dict("records")[0] if not df.empty else None
    except Exception:
        return None


# ============================================================
# HELPERS
# ============================================================

def _safe_str(val, default=""):
    if pd.isna(val):
        return default
    return str(val)


def _h(val):
    """HTML-escape a value for safe interpolation into HTML."""
    return _esc(str(val)) if val and not pd.isna(val) else ""


def _safe_url(val):
    """Return a URL safe for use in href, or '#' if suspicious."""
    url = str(val).strip() if val and not pd.isna(val) else ""
    if url and url.lower().startswith(("http://", "https://")):
        return _esc(url, quote=True)
    return "#"


def _to_str(val):
    if val is None:
        return None
    if isinstance(val, list):
        return ", ".join(str(v) for v in val)
    return str(val)


def _extract_json(text):
    if not text:
        return None
    cleaned = text.replace("```json\n", "").replace("```\n", "").replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    import re
    match = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', cleaned)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    return None


def _format_date_badge(job):
    from datetime import datetime
    posted = job.get("posted_at")
    found = job.get("discovered_at")
    date_str = None

    if pd.notna(posted) and posted:
        try:
            dt = pd.to_datetime(posted)
            days = (datetime.now() - dt.replace(tzinfo=None)).days
            if days <= 1:
                date_str = "today"
            elif days <= 7:
                date_str = f"{days}d ago"
            elif days <= 30:
                date_str = f"{days // 7}w ago"
            else:
                date_str = dt.strftime("%b %d")
        except Exception:
            pass

    if not date_str and pd.notna(found) and found:
        try:
            dt = pd.to_datetime(found)
            date_str = f"found {dt.strftime('%b %d')}"
        except Exception:
            pass

    if date_str:
        return f" &nbsp;&middot;&nbsp; {date_str}"
    return ""


def _build_resume_text_from_json(resume_json: dict) -> str:
    if not resume_json or "bullets" not in resume_json:
        return ""
    lines = []
    for role, bullets in resume_json.get("bullets", {}).items():
        lines.append(role)
        for i, b in enumerate(bullets, 1):
            lines.append(f"  Bullet {i}: {b}")
    return "\n".join(lines)


def generate_materials(job, user=None):
    """Single Gemini Flash call for cover letter, resume tips, similar roles, culture notes."""
    desc = _safe_str(job.get("description"))[:1200]
    culture_flags = _safe_str(job.get("culture_flags"))
    glassdoor = _safe_str(job.get("glassdoor_rating"))
    culture_context = ""
    if culture_flags or glassdoor:
        culture_context = f"\nCOMPANY CULTURE CONTEXT:\nGlassdoor: {glassdoor}\nFlags: {culture_flags}\n"

    # Use user's resume if available
    if user and user.get("resume_json"):
        try:
            resume_data = json.loads(user["resume_json"]) if isinstance(user["resume_json"], str) else user["resume_json"]
        except Exception:
            resume_data = {}
        resume_summary = resume_data.get("summary", "")
        resume_skills = resume_data.get("skills", "")
        resume_text = _build_resume_text_from_json(resume_data)
        user_name = user.get("name", "the candidate")
    else:
        resume_summary = ""
        resume_skills = ""
        resume_text = ""
        user_name = user.get("name", "the candidate") if user else "the candidate"

    prompt = f"""You are a job application assistant. Given a job description and {user_name}'s resume, produce ALL FOUR outputs below in a single JSON response.

JOB: "{job['title']}" at {job['company']}

JOB DESCRIPTION:
{desc}
{culture_context}
{user_name.upper()}'S RESUME:
Summary: {resume_summary}
Skills: {resume_skills}

{resume_text}

Return ONLY valid JSON with these 4 keys:

{{
  "cover_letter": "<full cover letter text, 250-300 words, 3 paragraphs: hook/evidence/close. Address to 'Hiring Manager'. Open with an observation about the role, not 'I'm writing to express'. Pick 2 concrete resume examples with numbers. Tone: direct, confident, conversational. Sign '{user_name}'. Avoid: passion, excited, thrilled, leverage, synergy, adept, I believe, I'm confident.>",

  "resume_tips": "<3-5 specific suggestions. Each: name the exact role and bullet, quote current wording, suggest revision, one-sentence reason. Plain language only. Don't invent experience. If a bullet is strong, say keep as-is.>",

  "similar_roles": "<3-5 related job titles to also search for, based on this role's requirements and background. Brief, comma-separated list.>",

  "culture_notes": "<2-3 sentences about what working at {job['company']} might be like, based on available culture data, Glassdoor info, and the job description tone. Be honest — flag concerns if any. If no culture data available, note that.>"
}}"""

    response = ai_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config={"temperature": 0.5},
    )
    return _extract_json(response.text) or {}


def answer_application_question(job, question, user=None):
    """Use Gemini Flash to draft a tailored answer to an application question."""
    desc = _safe_str(job.get("description"))[:1200]

    if user and user.get("resume_json"):
        try:
            resume_data = json.loads(user["resume_json"]) if isinstance(user["resume_json"], str) else user["resume_json"]
        except Exception:
            resume_data = {}
        resume_summary = resume_data.get("summary", "")
        resume_skills = resume_data.get("skills", "")
        resume_text = _build_resume_text_from_json(resume_data)
        user_name = user.get("name", "the candidate")
    else:
        resume_summary = ""
        resume_skills = ""
        resume_text = ""
        user_name = user.get("name", "the candidate") if user else "the candidate"

    prompt = f"""You are helping {user_name} answer an application question for the "{job['title']}" role at {job['company']}.

JOB DESCRIPTION:
{desc}

{user_name.upper()}'S RESUME:
Summary: {resume_summary}
Skills: {resume_skills}

{resume_text}

APPLICATION QUESTION:
{question}

RULES:
- Answer in first person as {user_name.split()[0]}.
- Be specific — pull a real example from the resume that best answers this question.
- Keep it tight: 100-200 words unless the question clearly demands more.
- Tone: Direct, human, conversational.
- Do NOT use: "passion", "excited", "thrilled", "leverage", "synergy", "adept", "I believe", "I'm confident", "unique opportunity".
- Do NOT invent experience. Only draw from what's in the resume.
- If the question asks about something not in the resume, be honest and pivot to the closest relevant experience.

Return ONLY the answer text."""

    response = ai_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config={"temperature": 0.6},
    )
    return response.text.strip()


def load_contacts(user_id):
    if not user_id:
        return pd.DataFrame()
    try:
        return query_df("SELECT * FROM contacts WHERE user_id = ?", params=(user_id,))
    except Exception:
        return pd.DataFrame()


def save_contacts(df_contacts, user_id):
    if not user_id:
        return
    conn = get_connection()
    conn.execute("DELETE FROM contacts WHERE user_id = ?", (user_id,))
    for _, row in df_contacts.iterrows():
        conn.execute(
            "INSERT INTO contacts (user_id, first_name, last_name, email, company, position, connected_on) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, row.get("First Name"), row.get("Last Name"), row.get("Email Address"),
             row.get("Company"), row.get("Position"), row.get("Connected On")),
        )
    conn.commit()


def find_network_matches(jobs_df, contacts_df):
    if contacts_df.empty:
        return {}
    matches = {}
    contact_companies = contacts_df[contacts_df["company"].notna()].copy()
    contact_companies["company_lower"] = contact_companies["company"].str.lower().str.strip()
    for _, job in jobs_df.iterrows():
        company = str(job.get("company", "")).lower().strip()
        if not company:
            continue
        matched = contact_companies[
            contact_companies["company_lower"].str.contains(company, na=False)
            | contact_companies["company_lower"].apply(lambda c: company in c if c else False)
        ]
        if not matched.empty:
            matches[int(job["id"])] = matched.to_dict("records")
    return matches


# ============================================================
# ONBOARDING / LOGIN FLOW
# ============================================================

def show_onboarding():
    """Show login/register page. Returns user dict if logged in, None otherwise."""
    st.markdown('<div class="scout-title">The <em>Scout</em></div>', unsafe_allow_html=True)
    st.markdown(SUBTITLE_ANIMATED, unsafe_allow_html=True)
    st.markdown("---")

    tab_login, tab_register, tab_reset = st.tabs(["Log in", "Create account", "Reset password"])

    with tab_login:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in")
            if submitted:
                user = login_user(username, password)
                if user:
                    st.session_state["user_id"] = user["id"]
                    _set_session_cookie(user["id"])
                    st.rerun()
                else:
                    st.error("Invalid username or password")

    with tab_register:
        with st.form("register_form"):
            new_username = st.text_input("Choose a username")
            new_name = st.text_input("Your full name")
            new_email = st.text_input("Email")
            new_password = st.text_input("Choose a password", type="password")
            new_password2 = st.text_input("Confirm password", type="password")
            submitted = st.form_submit_button("Create account")
            if submitted:
                if not new_username or not new_password:
                    st.error("Username and password are required")
                elif new_password != new_password2:
                    st.error("Passwords don't match")
                elif len(new_password) < 6:
                    st.error("Password must be at least 6 characters")
                else:
                    if register_user(new_username, new_password, new_name, new_email):
                        user = login_user(new_username, new_password)
                        st.session_state["user_id"] = user["id"]
                        _set_session_cookie(user["id"])
                        st.rerun()
                    else:
                        st.error("Username already taken")

    with tab_reset:
        with st.form("reset_form"):
            reset_username = st.text_input("Username")
            reset_email = st.text_input("Email on file")
            reset_pw = st.text_input("New password", type="password")
            reset_pw2 = st.text_input("Confirm new password", type="password")
            submitted = st.form_submit_button("Reset password")
            if submitted:
                if not reset_username or not reset_email or not reset_pw:
                    st.error("All fields are required")
                elif reset_pw != reset_pw2:
                    st.error("Passwords don't match")
                elif len(reset_pw) < 6:
                    st.error("Password must be at least 6 characters")
                elif reset_password(reset_username, reset_email, reset_pw):
                    st.success("Password reset. You can now log in.")
                else:
                    st.error("Username and email don't match any account")


def show_profile_setup(user):
    """Show resume upload and goals setup — works for new and returning users."""
    is_editing = bool(user.get("resume_json") or user.get("goals_text"))

    # Sidebar with account controls during setup
    with st.sidebar:
        display_name = _h(user.get("name") or user["username"])
        st.markdown(
            f'<div style="font-family: Instrument Serif, serif; font-size: 1.2rem; '
            f'margin-bottom: 0.25rem;">{display_name}</div>',
            unsafe_allow_html=True,
        )
        if st.button("Log out", key="setup_logout_btn"):
            _clear_session_cookie()
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    if is_editing:
        st.markdown(f'<div class="setup-illustration">{SVG_COMPASS}</div>', unsafe_allow_html=True)
        st.markdown('<div class="onboard-title">Edit your profile</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="section-hint">Update your resume or search criteria. Changes take effect on your next Scout run.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(f'<div class="setup-illustration">{SVG_MAP}</div>', unsafe_allow_html=True)
        st.markdown('<div class="onboard-title">Set up your profile</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="section-hint">Two steps to get started: upload your resume, then describe what you\'re looking for. The Scout uses both to find and score jobs tailored to you.</div>',
            unsafe_allow_html=True,
        )

    # Track completion of each step
    existing_resume = None
    if user.get("resume_json"):
        try:
            existing_resume = json.loads(user["resume_json"]) if isinstance(user["resume_json"], str) else user["resume_json"]
        except Exception:
            pass
    has_resume = existing_resume is not None or "parsed_resume" in st.session_state
    has_goals = bool(user.get("goals_text"))

    # ── Step 1: Resume ──
    step1_status = " ~" if has_resume else ""
    st.markdown(f"### Step 1: Resume{step1_status}")
    if not has_resume:
        st.markdown(
            '<div class="section-hint">Upload a PDF of your resume. The Scout will extract your experience, skills, and accomplishments to personalize job scoring and application materials.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="section-hint">Your resume is on file. Upload a new one below to replace it.</div>',
            unsafe_allow_html=True,
        )

    uploaded_pdf = st.file_uploader("Upload your resume (PDF)", type=["pdf"], label_visibility="collapsed")

    if uploaded_pdf is not None:
        if st.button("Parse resume with AI", type="primary"):
            with st.spinner("Reading your resume..."):
                parsed = parse_resume_pdf(uploaded_pdf.read())
            if parsed and parsed.get("bullets"):
                st.session_state["parsed_resume"] = parsed
                st.success("Resume parsed — review the extracted data below, then save.")
            else:
                st.error("Could not parse resume. Try uploading a different format.")

    if "parsed_resume" in st.session_state:
        parsed = st.session_state["parsed_resume"]
        st.markdown("**Extracted resume data** — review before saving:")
        st.json(parsed)
        if st.button("Save resume", type="primary"):
            update_user_field(user["id"], "resume_json", json.dumps(parsed))
            del st.session_state["parsed_resume"]
            st.success("Resume saved.")
            st.rerun()
    elif existing_resume:
        with st.expander("View current resume on file"):
            st.json(existing_resume)

    st.markdown("---")

    # ── Step 2: Search criteria ──
    step2_status = " ~" if has_goals else ""
    st.markdown(f"### Step 2: Search criteria{step2_status}")
    st.markdown(
        '<div class="section-hint">Tell The Scout what you\'re looking for. The more specific you are, the better it scores jobs for you. Include:</div>',
        unsafe_allow_html=True,
    )
    st.markdown("""
- **Target roles** — exact titles you'd apply for (e.g. "Senior PM", "Customer Success Manager", "Solutions Engineer")
- **Industries / company types** — SaaS, fintech, healthcare, agencies, etc.
- **Location requirements** — remote only, hybrid OK, specific cities or time zones
- **Bonus skills or keywords** — things that make a role extra appealing to you
- **Hard deal-breakers** — things you want The Scout to automatically skip
""")

    current_goals = user.get("goals_text") or ""
    goals = st.text_area(
        "What are you looking for?",
        value=current_goals,
        height=200,
        label_visibility="collapsed",
        placeholder="Example:\n\nUS Remote only. Looking for Customer Success Manager or Account Manager roles at B2B SaaS companies (50-500 employees).\n\nIdeal: roles with a book of business, strategic accounts, and cross-functional work with Product.\n\nAlso interested in: Solutions Consultant, Client Partner, Onboarding Lead.\n\nBonus: experience with enterprise clients, Salesforce, data-driven QBRs.\n\nSkip: on-site roles, agencies, entry-level, roles requiring travel >20%.",
    )

    # Determine what changed
    goals_changed = goals.strip() != current_goals.strip()

    # Refresh resume reference in case it was just saved
    if not existing_resume and user.get("resume_json"):
        try:
            existing_resume = json.loads(user["resume_json"]) if isinstance(user["resume_json"], str) else user["resume_json"]
        except Exception:
            pass
    resume_data = existing_resume or st.session_state.get("parsed_resume")

    if st.button("Save search criteria", type="primary"):
        if not goals.strip():
            st.warning("Write something about what you're looking for first.")
        else:
            update_user_field(user["id"], "goals_text", goals)
            if resume_data:
                with st.spinner("Generating your personalized scoring criteria..."):
                    prompt = generate_scoring_prompt(resume_data, goals)
                    update_user_field(user["id"], "scoring_prompt", prompt)
                st.success("Search criteria and scoring prompt saved.")
            else:
                st.success("Search criteria saved. Upload a resume to unlock personalized scoring.")
            st.rerun()

    st.markdown("---")

    # ── Continue / Back to dashboard ──
    # Refresh completion state after potential saves above
    has_resume_now = bool(user.get("resume_json")) or "parsed_resume" in st.session_state
    has_goals_now = bool(user.get("goals_text"))

    if is_editing:
        if st.button("Back to dashboard", type="primary"):
            st.session_state["profile_setup_done"] = True
            st.rerun()
    elif has_resume_now and has_goals_now:
        st.success("You're all set! Click below to start discovering roles.")
        if st.button("Go to dashboard", type="primary"):
            st.session_state["profile_setup_done"] = True
            st.rerun()
    elif has_resume_now or has_goals_now:
        remaining = "search criteria" if not has_goals_now else "resume"
        st.info(f"Almost there — add your {remaining} above to get the best results.")
        if st.button("Skip for now — go to dashboard"):
            st.session_state["profile_setup_done"] = True
            st.rerun()
    else:
        st.info("Complete the steps above to get started.")
        if st.button("Skip for now — go to dashboard"):
            st.session_state["profile_setup_done"] = True
            st.rerun()


# ============================================================
# MAIN APP FLOW
# ============================================================

# Check if user is logged in — try restoring from cookie first
if "user_id" not in st.session_state:
    cookie_uid = _get_cookie_user_id()
    if cookie_uid:
        st.session_state["user_id"] = cookie_uid
    else:
        show_onboarding()
        st.stop()

# Load current user
current_user = get_user(st.session_state["user_id"])
if not current_user:
    _clear_session_cookie()
    del st.session_state["user_id"]
    st.rerun()

# Check if profile needs setup (no resume yet)
# Default profile_setup_done to True if user already has a resume
if "profile_setup_done" not in st.session_state:
    st.session_state["profile_setup_done"] = bool(current_user.get("resume_json"))
needs_setup = not st.session_state["profile_setup_done"]

# --- Header ---
st.markdown('<div class="scout-title">The <em>Scout</em></div>', unsafe_allow_html=True)
st.markdown(SUBTITLE_ANIMATED, unsafe_allow_html=True)

# Show profile setup if needed
if needs_setup:
    show_profile_setup(current_user)
    st.stop()

# Greeting (use US Eastern as default — server may be UTC on Streamlit Cloud)
from datetime import datetime as _dt
try:
    from zoneinfo import ZoneInfo
    _hour = _dt.now(ZoneInfo("America/New_York")).hour
except Exception:
    _hour = _dt.now().hour
_first_name = _h((current_user.get("name") or "").split()[0]) if current_user.get("name") else ""
if _hour < 12:
    _greeting = f"Good morning{', ' + _first_name if _first_name else ''}."
elif _hour < 17:
    _greeting = f"Good afternoon{', ' + _first_name if _first_name else ''}."
else:
    _greeting = f"Good evening{', ' + _first_name if _first_name else ''}."
st.markdown(f'<div class="greeting">{_greeting}</div>', unsafe_allow_html=True)

# Last run info + Scout button
last_run = load_last_run(user_id=current_user["id"])
_scout_label = "Scout again" if last_run else "Start scouting"

run_col, btn_col = st.columns([3, 1])
with run_col:
    if last_run:
        _api_info = ""
        if last_run.get("api_calls"):
            _api_info = f' &nbsp;&middot;&nbsp; {last_run["api_calls"]} AI calls'
        st.markdown(
            f'<div class="run-info">'
            f'Last scouted {last_run["started_at"]} &nbsp;&middot;&nbsp; '
            f'{last_run["jobs_found"]} found &nbsp;&middot;&nbsp; '
            f'{last_run["jobs_scored"]} scored &nbsp;&middot;&nbsp; '
            f'{last_run["jobs_enriched"]} researched'
            f'{_api_info}'
            f'</div>',
            unsafe_allow_html=True,
        )
with btn_col:
    st.markdown('<div class="scout-btn">', unsafe_allow_html=True)
    scout_clicked = st.button(_scout_label)
    st.markdown('</div>', unsafe_allow_html=True)

# Partial pipeline controls
with st.expander("Run specific phases (saves tokens)"):
    st.markdown(
        '<span style="font-size: 0.85rem; color: #9C9488;">'
        'Pick individual phases instead of running the full pipeline. '
        'Discover scans job boards, Score rates fit, Enrich researches top picks, Draft writes outreach emails.'
        '</span>',
        unsafe_allow_html=True,
    )
    pc1, pc2, pc3, pc4, pc5 = st.columns([1, 1, 1, 1, 1])
    with pc1:
        _phase_discover = st.button("Discover", key="phase_discover", use_container_width=True)
    with pc2:
        _phase_score = st.button("Score", key="phase_score", use_container_width=True)
    with pc3:
        _phase_enrich = st.button("Enrich", key="phase_enrich", use_container_width=True)
    with pc4:
        _phase_draft = st.button("Draft", key="phase_draft", use_container_width=True)
    with pc5:
        _phase_discover_score = st.button("Discover + Score", key="phase_disc_score", use_container_width=True)

    st.markdown("---")
    st.markdown(
        '<span style="font-size: 0.85rem; color: #9C9488;">'
        'Re-score clears all existing scores and re-evaluates every job with your current scoring criteria. '
        'Useful after updating your profile or search goals.'
        '</span>',
        unsafe_allow_html=True,
    )
    rc1, rc2 = st.columns([1, 3])
    with rc1:
        _rescore_clicked = st.button("Re-score all", key="rescore_all", type="secondary", use_container_width=True)
    with rc2:
        _regen_and_rescore = st.button("Regenerate prompt + re-score", key="regen_rescore", type="secondary", use_container_width=True)

# Handle re-score actions (must run before the normal pipeline trigger)
if _regen_and_rescore or _rescore_clicked:
    with st.status("Re-scoring all jobs...", expanded=True) as status:
        progress = st.empty()

        def _update_progress_rescore(msg):
            progress.markdown(
                f'<div class="scout-running">~ {msg}</div>',
                unsafe_allow_html=True,
            )

        try:
            conn = get_connection()

            # Regenerate scoring prompt if requested
            if _regen_and_rescore and current_user.get("resume_json"):
                _update_progress_rescore("Regenerating your scoring prompt with tighter criteria...")
                try:
                    rd = json.loads(current_user["resume_json"]) if isinstance(current_user["resume_json"], str) else current_user["resume_json"]
                    new_prompt = generate_scoring_prompt(rd, current_user.get("goals_text", ""))
                    update_user_field(current_user["id"], "scoring_prompt", new_prompt)
                    current_user["scoring_prompt"] = new_prompt
                    _update_progress_rescore("New scoring prompt generated")
                except Exception:
                    _update_progress_rescore("Prompt regeneration failed — re-scoring with existing prompt")

            # Clear this user's scores only (keep status, cover letters, etc.)
            _update_progress_rescore("Clearing your existing scores...")
            conn.execute(
                "UPDATE user_jobs SET score = NULL, tier = NULL, score_reasoning = NULL WHERE user_id = ?",
                (current_user["id"],),
            )
            conn.commit()

            # Run score phase only — writes to user_jobs for this user
            from scout import score as _run_score
            _update_progress_rescore("Scoring all jobs with updated criteria...")
            score_result = _run_score(conn, current_user.get("scoring_prompt"), _update_progress_rescore, user_id=current_user["id"])
            _api_count = score_result.get("api_calls", 0)
            _scored = score_result.get("scored", 0)
            _stale = score_result.get("skipped_stale", 0)
            _label = f"Done — {_scored} jobs re-scored, {_api_count} AI calls"
            if _stale:
                _label += f", {_stale} stale skipped"
            status.update(label=_label, state="complete", expanded=False)
            st.cache_resource.clear()
            st.rerun()
        except Exception:
            status.update(label="Something went wrong", state="error")
            st.error("Re-scoring failed. Please try again.")

# Determine which phases to run
_selected_phases = None
_run_triggered = False
if scout_clicked:
    _run_triggered = True
    _selected_phases = None  # full pipeline
elif _phase_discover:
    _run_triggered = True
    _selected_phases = {"discover"}
elif _phase_score:
    _run_triggered = True
    _selected_phases = {"score"}
elif _phase_enrich:
    _run_triggered = True
    _selected_phases = {"enrich"}
elif _phase_draft:
    _run_triggered = True
    _selected_phases = {"draft"}
elif _phase_discover_score:
    _run_triggered = True
    _selected_phases = {"discover", "score"}

if _run_triggered:
    _phase_label = "full scout" if not _selected_phases else " + ".join(sorted(_selected_phases))
    with st.status(f"Running {_phase_label}...", expanded=True) as status:
        progress = st.empty()
        progress.markdown(
            '<div class="scout-running">~ starting up...</div>',
            unsafe_allow_html=True,
        )

        def _update_progress(msg):
            progress.markdown(
                f'<div class="scout-running">~ {msg}</div>',
                unsafe_allow_html=True,
            )

        try:
            conn = get_connection()
            # Build user-specific email bullets from resume
            user_bullets = None
            if current_user.get("resume_json"):
                try:
                    rd = json.loads(current_user["resume_json"]) if isinstance(current_user["resume_json"], str) else current_user["resume_json"]
                    bullet_lines = []
                    for role, blist in rd.get("bullets", {}).items():
                        for b in blist:
                            bullet_lines.append(f"- {b}")
                    if bullet_lines:
                        user_bullets = "\n".join(bullet_lines)
                except Exception:
                    pass
            result = run_pipeline(
                conn,
                scoring_system=current_user.get("scoring_prompt"),
                user_name=current_user.get("name") or "the candidate",
                user_bullets=user_bullets,
                on_progress=_update_progress,
                phases=_selected_phases,
                user_id=current_user["id"],
            )
            _api_count = result.get("api_calls", 0)
            _stale_skipped = result.get("scored", {}).get("skipped_stale", 0) + result.get("enriched", {}).get("skipped_stale", 0)
            _done_label = f"Done — {_api_count} AI call{'s' if _api_count != 1 else ''} used"
            if _stale_skipped:
                _done_label += f", {_stale_skipped} stale job{'s' if _stale_skipped != 1 else ''} skipped"
            status.update(label=_done_label, state="complete", expanded=False)
            st.cache_resource.clear()
            st.rerun()
        except Exception as e:
            status.update(label="Something went wrong", state="error")
            st.error("Something went wrong during scouting. Please try again.")

# --- Load Data ---
user_id = current_user["id"]
df = load_jobs_for_user(user_id)

# Normalize inconsistent tier labels from different scoring runs
_TIER_MAP = {"strong": "tier1", "solid": "tier2", "mediocre": "no_match", "weak": "no_match",
             "hard reject": "no_match", "hard_reject": "no_match", "n/a": "no_match"}
if not df.empty and "tier" in df.columns:
    df["tier"] = df["tier"].apply(lambda t: _TIER_MAP.get(str(t).lower().strip(), t) if pd.notna(t) else t)

# --- Sidebar ---
with st.sidebar:
    # Account section at top
    display_name = _h(current_user.get("name") or current_user["username"])
    st.markdown(
        f'<div style="font-family: Instrument Serif, serif; font-size: 1.2rem; '
        f'margin-bottom: 0.25rem;">{display_name}</div>',
        unsafe_allow_html=True,
    )
    acct_col1, acct_col2 = st.columns(2)
    with acct_col1:
        if st.button("Edit profile", key="edit_profile_btn", use_container_width=True):
            st.session_state["profile_setup_done"] = False
            st.rerun()
    with acct_col2:
        if st.button("Log out", key="logout_btn", use_container_width=True):
            _clear_session_cookie()
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    st.divider()

    # Filters only make sense when there are jobs
    if not df.empty:
        st.markdown(
            '<div style="font-family: Instrument Serif, serif; font-size: 1.4rem; '
            'margin-bottom: 1rem;">Narrow it down</div>',
            unsafe_allow_html=True,
        )

        score_range = st.slider("Score range", 0, 100, (0, 100))

        platforms = st.multiselect(
            "Platform",
            options=df["platform"].dropna().unique().tolist(),
            default=df["platform"].dropna().unique().tolist(),
        )

        tiers = st.multiselect(
            "Tier",
            options=[t for t in df["tier"].dropna().unique().tolist()],
            default=[t for t in df["tier"].dropna().unique().tolist()],
            help="**tier1** = Strong match (80-89) — core responsibilities align with your expertise\n\n"
                 "**tier2** = Solid fit (65-79) — good role but missing 1-2 alignment factors\n\n"
                 "**no_match** = Weak/mediocre fit (below 65)\n\n"
                 "**stale** = Posted over 30 days ago, skipped to save tokens",
        )

        statuses_filter = st.multiselect(
            "Status",
            options=STATUSES,
            default=STATUSES,
        )

        st.divider()

    # LinkedIn network
    st.markdown(
        '<div style="font-family: Instrument Serif, serif; font-size: 1.2rem; '
        'margin-bottom: 0.5rem;">LinkedIn network</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="section-hint">Upload your LinkedIn connections CSV to see who you know at target companies.</div>',
        unsafe_allow_html=True,
    )
    uploaded_csv = st.file_uploader("Connections CSV", type=["csv"], label_visibility="collapsed")
    if uploaded_csv is not None:
        try:
            csv_df = pd.read_csv(uploaded_csv, skiprows=3)
            save_contacts(csv_df, user_id)
            st.success(f"Loaded {len(csv_df)} connections")
        except Exception as e:
            st.error("CSV import failed. Please check the file format and try again.")

if df.empty:
    st.markdown(
        f'<div class="empty-state">'
        f'{SVG_BINOCULARS}'
        f'<div class="empty-state-heading">No roles scouted yet</div>'
        f'<div class="empty-state-body">'
        f'Hit <strong>Start scouting</strong> above to search across job boards. '
        f'The Scout will find, score, and research roles tailored to your profile.'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.stop()

# Load contacts for network matching
contacts_df = load_contacts(user_id)

# Apply filters
filtered = df[
    (df["score"].fillna(0) >= score_range[0])
    & (df["score"].fillna(0) <= score_range[1])
    & (df["platform"].isin(platforms))
    & (df["tier"].fillna("no_match").isin(tiers))
    & (df["status"].isin(statuses_filter))
]

# Compute network matches
network_matches = find_network_matches(df, contacts_df) if not contacts_df.empty else {}

# --- Metrics ---
scored_df = df[df["score"].notna()]
best_count = len(scored_df[scored_df["score"] > 70]) if not scored_df.empty else 0
warm_count = len(scored_df[(scored_df["score"] >= 50) & (scored_df["score"] <= 70)]) if not scored_df.empty else 0
applied_count = len(df[df["status"] == "Applied"])

col1, col2, col3, col4 = st.columns(4)
col1.metric("Scouted", len(df))
col2.metric("Best shots", best_count)
col3.metric("Worth a look", warm_count)
col4.metric("Applied", applied_count)

if not scored_df.empty and best_count == 0 and warm_count == 0:
    st.markdown(
        '<div class="section-hint" style="margin-top:0.5rem;">'
        'Roles have been found but none scored above 50 yet. Try refining your search criteria or running Scout again.'
        '</div>',
        unsafe_allow_html=True,
    )

# Tier legend
_unscored_count = len(df[df["score"].isna()])
_tier_legend = (
    '<div style="display:flex; gap:1.5rem; flex-wrap:wrap; font-size:0.78rem; color:#888; margin-top:0.5rem;">'
    '<span><strong style="color:#2e7d32;">tier1</strong> Strong match (80-89)</span>'
    '<span><strong style="color:#1565c0;">tier2</strong> Solid fit (65-79)</span>'
    '<span><strong style="color:#757575;">no_match</strong> Below 65</span>'
)
if _unscored_count:
    _tier_legend += f'<span style="color:#aaa;">{_unscored_count} unscored — run Score to evaluate</span>'
_tier_legend += '</div>'
st.markdown(_tier_legend, unsafe_allow_html=True)

st.markdown(TILDE_DIVIDER, unsafe_allow_html=True)

_TIER_LABELS = {"tier1": "Strong match", "tier2": "Solid fit", "no_match": "Low match", "stale": "Stale"}

def _tier_label(tier_val):
    return _TIER_LABELS.get(str(tier_val).lower().strip(), str(tier_val) if pd.notna(tier_val) else "")

# --- Best Shots ---
hot = filtered[filtered["score"] > 70].copy()
if not hot.empty:
    st.markdown(
        '<div class="section-header">Your best shots</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="section-hint">Roles that fit your profile well. Enriched with hiring manager info and draft outreach.</div>',
        unsafe_allow_html=True,
    )

    for _, job in hot.iterrows():
        score_val = int(job["score"])
        job_id_int = int(job["id"])
        network_badge = '<span class="network-badge">You know someone here</span>' if job_id_int in network_matches else ''

        card_html = f"""
        <div class="job-card">
            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                <div>
                    <div class="job-card-title">{_h(job['title'])}</div>
                    <div class="job-card-company">{_h(job['company'])}{network_badge}</div>
                    <div class="job-card-meta">{_h(job['platform']).upper()} &nbsp;&middot;&nbsp; {_tier_label(job.get('tier', ''))} &nbsp;&middot;&nbsp; Score {score_val}{_format_date_badge(job)}</div>
                </div>
                <div class="score-badge">{score_val}</div>
            </div>
        """

        details = []
        sal_min = job.get("salary_min")
        sal_max = job.get("salary_max")
        if pd.notna(sal_min) and pd.notna(sal_max) and sal_min and sal_max:
            sal_src = _safe_str(job.get("salary_source"))
            src_label = f" ({_h(sal_src)})" if sal_src else ""
            details.append(f"<strong>Salary:</strong> ${int(sal_min):,} – ${int(sal_max):,}{src_label}")
        gd = _safe_str(job.get("glassdoor_rating"))
        cf = _safe_str(job.get("culture_flags"))
        culture_parts = []
        if gd and gd.lower() != "unknown":
            culture_parts.append(f"Glassdoor {_h(gd)}")
        if cf and cf.lower() != "unknown":
            culture_parts.append(_h(cf))
        if culture_parts:
            details.append(f"<strong>Culture:</strong> {' · '.join(culture_parts)}")
        if job.get("score_reasoning"):
            details.append(f"<strong>Fit:</strong> {_h(job['score_reasoning'])}")
        if job.get("hiring_manager_name") and job["hiring_manager_name"] != "Unknown":
            hm_title = _h(job.get("hiring_manager_title", ""))
            details.append(
                f"<strong>Reach out to:</strong> {_h(job['hiring_manager_name'])} ({hm_title})"
            )
        if job.get("company_win") and job["company_win"] != "No recent news found.":
            win_text = _h(job["company_win"][:120])
            details.append(f"<strong>Recent:</strong> {win_text}...")

        if details:
            card_html += '<div class="job-card-detail">' + "<br>".join(details) + "</div>"

        card_html += f"""
            <div style="margin-top: 0.8rem;">
                <a class="job-card-link" href="{_safe_url(job['url'])}" target="_blank">View posting &rarr;</a>
            </div>
        </div>
        """

        st.markdown(card_html, unsafe_allow_html=True)

        # Action row: status + generate materials
        job_id = int(job["id"])
        col_status, col_gen, col_spacer = st.columns([1.2, 1.2, 2.6])

        with col_status:
            current_status = job["status"] if job["status"] in STATUSES else "Unexplored"
            new_status = st.selectbox(
                "Status",
                STATUSES,
                index=STATUSES.index(current_status),
                key=f"status_{job_id}",
                label_visibility="collapsed",
            )
            if new_status != current_status:
                update_user_job_status(user_id, job_id, new_status)
                st.rerun()

        with col_gen:
            if st.button("Generate materials", key=f"gen_{job_id}"):
                try:
                    with st.spinner("Generating cover letter, resume tips, similar roles & culture notes..."):
                        materials = generate_materials(job, current_user)
                        save_user_materials(user_id, job_id, materials)
                        st.cache_resource.clear()
                        st.rerun()
                except Exception:
                    st.error("Failed to generate materials. Please try again.")

        # Expandable content
        if job.get("vibe_check_email"):
            with st.expander("Draft outreach email"):
                st.text_area(
                    "Personalize before sending:",
                    value=job["vibe_check_email"],
                    height=180,
                    key=f"email_{job_id}",
                    label_visibility="collapsed",
                )

        if job.get("cover_letter") and pd.notna(job.get("cover_letter")):
            with st.expander("Cover letter"):
                st.text_area(
                    "Edit and save:",
                    value=job["cover_letter"],
                    height=300,
                    key=f"cl_{job_id}",
                    label_visibility="collapsed",
                )

        if job.get("resume_tips") and pd.notna(job.get("resume_tips")):
            with st.expander("Resume suggestions"):
                st.markdown(job["resume_tips"])

        if job.get("similar_roles") and pd.notna(job.get("similar_roles")):
            with st.expander("Similar roles to search"):
                st.markdown(job["similar_roles"])

        if job.get("culture_notes") and pd.notna(job.get("culture_notes")):
            with st.expander("Culture notes"):
                st.markdown(job["culture_notes"])

        # Application question answerer
        with st.expander("Answer an application question"):
            app_q = st.text_input(
                "Paste the question here",
                key=f"appq_{job_id}",
                placeholder="e.g. What is one thing you built, shipped, or owned end-to-end?",
            )
            if app_q and st.button("Draft answer", key=f"appq_btn_{job_id}"):
                try:
                    with st.spinner("Drafting answer..."):
                        answer = answer_application_question(job, app_q, current_user)
                    st.text_area(
                        "Your draft:",
                        value=answer,
                        height=200,
                        key=f"appq_ans_{job_id}",
                        label_visibility="collapsed",
                    )
                except Exception:
                    st.error("Failed to draft answer. Please try again.")

st.markdown(TILDE_DIVIDER, unsafe_allow_html=True)

# --- Worth a Look ---
warm = filtered[(filtered["score"] >= 50) & (filtered["score"] <= 70)].copy()
if not warm.empty:
    st.markdown(
        '<div class="section-header">Worth a look</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="section-hint">Decent fit, but not a bullseye. Browse and decide.</div>',
        unsafe_allow_html=True,
    )

    for _, job in warm.iterrows():
        score_val = int(job["score"]) if pd.notna(job["score"]) else 0
        st.markdown(
            f'<div class="job-card" style="padding: 1rem 1.4rem;">'
            f'<div style="display: flex; justify-content: space-between; align-items: center;">'
            f'<div>'
            f'<span class="job-card-title" style="font-size: 1.05rem;">{_h(job["title"])}</span>'
            f'<span class="job-card-meta" style="margin-left: 0.8rem;">{_h(job["company"])} &middot; {score_val}</span>'
            f'</div>'
            f'<a class="job-card-link" href="{_safe_url(job["url"])}" target="_blank">View &rarr;</a>'
            f'</div></div>',
            unsafe_allow_html=True,
        )

st.markdown(TILDE_DIVIDER, unsafe_allow_html=True)

# --- Everything Else ---
st.markdown(
    '<div class="section-header">The full list</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="section-hint">Every role The Scout found, sorted by fit.</div>',
    unsafe_allow_html=True,
)

display_cols = ["title", "company", "platform", "score", "tier", "status", "posted_at", "discovered_at", "url"]
available_cols = [c for c in display_cols if c in filtered.columns]
st.dataframe(
    filtered[available_cols],
    width="stretch",
    hide_index=True,
    column_config={
        "url": st.column_config.LinkColumn("Link", display_text="Open"),
        "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
        "title": st.column_config.TextColumn("Role"),
        "company": st.column_config.TextColumn("Company"),
        "platform": st.column_config.TextColumn("Source"),
        "tier": st.column_config.TextColumn("Tier"),
        "status": st.column_config.TextColumn("Status"),
        "posted_at": st.column_config.DateColumn("Posted", format="MMM DD"),
        "discovered_at": st.column_config.DateColumn("Found", format="MMM DD"),
    },
)

# --- Network Matches ---
if network_matches:
    st.divider()
    st.markdown(
        '<div class="section-header">Network matches</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="section-hint">LinkedIn connections at companies with open roles.</div>',
        unsafe_allow_html=True,
    )
    for job_id, contacts in network_matches.items():
        job_row = df[df["id"] == job_id]
        if job_row.empty:
            continue
        job_row = job_row.iloc[0]
        for contact in contacts:
            name = _h(f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip())
            position = _h(contact.get("position", ""))
            company = _h(contact.get("company", ""))
            pos_label = f" — {position}" if position else ""
            st.markdown(
                f'<div class="job-card" style="padding: 0.8rem 1.4rem;">'
                f'<span class="job-card-title" style="font-size: 1rem;">{name}</span>'
                f'<span class="job-card-meta" style="margin-left: 0.6rem;">{company}{pos_label}</span>'
                f'<br><span class="job-card-meta">Role: {_h(job_row["title"])}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
