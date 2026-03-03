import streamlit as st
import pandas as pd
import sqlite3
import os
import json
import hashlib
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from scout import run_pipeline

load_dotenv(Path(__file__).parent / ".env")

DB_PATH = Path(__file__).parent / "job_tracker.db"
PROJECT_DIR = Path(__file__).parent
STATUSES = ["Unexplored", "Researched", "Applied", "Followed-Up"]

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
        padding: 0.6rem 0;
        border-bottom: 1px solid #E0D9CF;
        margin-bottom: 1.5rem;
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

    /* Hide Streamlit branding but keep sidebar toggle */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    [data-testid="stStatusWidget"] {display: none;}
    [data-testid="stToolbar"] {display: none;}

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

    /* Scout again button */
    .scout-btn > button {
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
    .scout-btn > button:hover {
        background: #C4653A !important;
        color: #F7F3ED !important;
    }
    .scout-btn > button:active, .scout-btn > button:focus {
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

    conn.commit()


ensure_schema()


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
    except Exception:
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
            return user
    return None


def get_user(user_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row:
        cols = [d[0] for d in conn.execute("SELECT * FROM users WHERE 1=0").description]
        return dict(zip(cols, row))
    return None


def update_user_field(user_id: int, field: str, value):
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
        contents=f"""Given this candidate's resume and job search goals, generate a scoring system prompt for evaluating job fit (0-100 scale).

RESUME:
{resume_str}

GOALS:
{goals_text or "General PM/TPM roles, US remote"}

Generate a prompt similar to this format but personalized to THIS candidate:
- Define the candidate's strengths in 2-3 sentences
- Define Tier 1 roles (base 80-95) — their ideal match
- Define Tier 2 roles (base 65-80) — strong adjacency
- List bonus keywords (+5 each)
- List realism modifiers (title mismatch penalties, etc.)
- Define hard rejects (score=0)
- End with: Return ONLY a JSON array with one object per job: [{{"id":<job_id>,"score":<0-100>,"tier":"tier1"|"tier2"|"no_match","reasoning":"<1 sentence>"}}]

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


def load_last_run():
    try:
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

    # Use user's resume if available, otherwise fall back to Lee's hardcoded
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
        resume_summary = "Strategic Leader with 10+ years of experience in SaaS and eCommerce lifecycle management."
        resume_skills = "SaaS Lifecycle Management, Stakeholder Management, JIRA, AI-collaboration tools, Cross-functional team management"
        resume_text = ""  # Legacy mode without user
        user_name = "Lee Frank"

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
        resume_summary = "Strategic Leader with 10+ years of experience in SaaS and eCommerce lifecycle management."
        resume_skills = "SaaS Lifecycle Management, Stakeholder Management, JIRA, AI-collaboration tools"
        resume_text = ""
        user_name = "Lee Frank"

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


def load_contacts(user_id=None):
    try:
        if user_id:
            return query_df("SELECT * FROM contacts WHERE user_id = ?", params=(user_id,))
        return query_df("SELECT * FROM contacts")
    except Exception:
        return pd.DataFrame()


def save_contacts(df_contacts, user_id=None):
    conn = get_connection()
    if user_id:
        conn.execute("DELETE FROM contacts WHERE user_id = ?", (user_id,))
    else:
        conn.execute("DELETE FROM contacts")
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
    st.markdown(
        '<div class="scout-subtitle">Your creative-tech job hunter</div>',
        unsafe_allow_html=True,
    )
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
    """Show resume upload and goals setup for new users."""
    st.markdown('<div class="onboard-title">Set up your profile</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-hint">Upload your resume and tell The Scout what you\'re looking for.</div>',
        unsafe_allow_html=True,
    )

    # Resume upload
    st.markdown("**Resume (PDF)**")
    uploaded_pdf = st.file_uploader("Upload your resume", type=["pdf"], label_visibility="collapsed")

    existing_resume = None
    if user.get("resume_json"):
        try:
            existing_resume = json.loads(user["resume_json"]) if isinstance(user["resume_json"], str) else user["resume_json"]
        except Exception:
            pass

    if uploaded_pdf is not None:
        if st.button("Parse resume with AI"):
            with st.spinner("Reading your resume..."):
                parsed = parse_resume_pdf(uploaded_pdf.read())
            if parsed and parsed.get("bullets"):
                st.session_state["parsed_resume"] = parsed
                st.success("Resume parsed successfully")
            else:
                st.error("Could not parse resume. Try uploading a different format.")

    if "parsed_resume" in st.session_state:
        parsed = st.session_state["parsed_resume"]
        st.markdown("**Extracted resume data** (review and edit below)")
        st.json(parsed)

        if st.button("Save resume"):
            update_user_field(user["id"], "resume_json", json.dumps(parsed))
            st.success("Resume saved")
            del st.session_state["parsed_resume"]
            st.rerun()
    elif existing_resume:
        st.markdown("**Current resume on file**")
        st.json(existing_resume)

    st.markdown("---")

    # Goals
    st.markdown("**What are you looking for?**")
    current_goals = user.get("goals_text") or ""
    goals = st.text_area(
        "Describe your ideal roles, industries, deal-breakers, etc.",
        value=current_goals,
        height=150,
        label_visibility="collapsed",
        placeholder="e.g. Remote PM/TPM roles at mid-market SaaS companies. Interested in design tools, creative tech, developer tools. No agencies. No roles requiring security clearance.",
    )

    if st.button("Save goals & generate scoring prompt"):
        update_user_field(user["id"], "goals_text", goals)
        # Generate scoring prompt from resume + goals
        resume_data = existing_resume or (st.session_state.get("parsed_resume"))
        if resume_data:
            with st.spinner("Generating your personalized scoring criteria..."):
                prompt = generate_scoring_prompt(resume_data, goals)
                update_user_field(user["id"], "scoring_prompt", prompt)
            st.success("Scoring prompt generated and saved")
        else:
            st.warning("Upload a resume first so we can generate personalized scoring criteria")
        st.rerun()

    st.markdown("---")
    if st.button("Continue to dashboard"):
        st.session_state["profile_setup_done"] = True
        st.rerun()


# ============================================================
# MAIN APP FLOW
# ============================================================

# Check if user is logged in
if "user_id" not in st.session_state:
    show_onboarding()
    st.stop()

# Load current user
current_user = get_user(st.session_state["user_id"])
if not current_user:
    del st.session_state["user_id"]
    st.rerun()

# Check if profile needs setup (no resume yet)
# Default profile_setup_done to True if user already has a resume
if "profile_setup_done" not in st.session_state:
    st.session_state["profile_setup_done"] = bool(current_user.get("resume_json"))
needs_setup = not st.session_state["profile_setup_done"]

# --- Header ---
header_left, header_right = st.columns([3, 1])
with header_left:
    st.markdown('<div class="scout-title">The <em>Scout</em></div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="scout-subtitle">Your creative-tech job hunter</div>',
        unsafe_allow_html=True,
    )
with header_right:
    st.markdown("<div style='height: 2.5rem'></div>", unsafe_allow_html=True)
    scout_col = st.container()

# User info bar + logout
user_col1, user_col2 = st.columns([4, 1])
with user_col1:
    st.markdown(
        f'<div class="section-hint">Logged in as <strong>{current_user.get("name") or current_user["username"]}</strong></div>',
        unsafe_allow_html=True,
    )
with user_col2:
    if st.button("Log out", key="logout_btn"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# Show profile setup if needed
if needs_setup:
    show_profile_setup(current_user)
    st.stop()

# Last run info
last_run = load_last_run()
if last_run:
    st.markdown(
        f'<div class="run-info">'
        f'Last scouted {last_run["started_at"]} &nbsp;&middot;&nbsp; '
        f'{last_run["jobs_found"]} found &nbsp;&middot;&nbsp; '
        f'{last_run["jobs_scored"]} scored &nbsp;&middot;&nbsp; '
        f'{last_run["jobs_enriched"]} researched'
        f'</div>',
        unsafe_allow_html=True,
    )

# --- Scout Again Button ---
with scout_col:
    st.markdown('<div class="scout-btn">', unsafe_allow_html=True)
    if st.button("Scout again"):
        st.markdown('</div>', unsafe_allow_html=True)
        with st.status("Scouting for new roles...", expanded=True) as status:
            progress = st.empty()
            progress.markdown(
                '<div class="scout-running">~ discovering roles across job boards...</div>',
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
                )
                status.update(label="Done scouting", state="complete", expanded=False)
                st.cache_resource.clear()
                st.rerun()
            except Exception as e:
                status.update(label="Something went wrong", state="error")
                st.code(str(e)[-500:] if str(e) else "Unknown error")
    else:
        st.markdown('</div>', unsafe_allow_html=True)

# --- Load Data ---
user_id = current_user["id"]
df = load_jobs_for_user(user_id)

if df.empty:
    st.markdown(
        '<div class="section-hint" style="margin-top:3rem; font-size:1rem;">'
        "Nothing here yet. Click <strong>Scout again</strong> to start discovering roles."
        "</div>",
        unsafe_allow_html=True,
    )
    st.stop()

# --- Sidebar Filters ---
with st.sidebar:
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
    )

    statuses_filter = st.multiselect(
        "Status",
        options=STATUSES,
        default=STATUSES,
    )

    st.divider()

    # Profile management
    st.markdown(
        '<div style="font-family: Instrument Serif, serif; font-size: 1.2rem; '
        'margin-bottom: 0.5rem;">Your profile</div>',
        unsafe_allow_html=True,
    )
    if st.button("Edit profile / resume", key="edit_profile_btn"):
        st.session_state["profile_setup_done"] = False
        st.rerun()

    st.divider()
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
            st.error(f"CSV import failed: {e}")

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
if not scored_df.empty:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Scouted", len(df))
    col2.metric("Best shots", len(scored_df[scored_df["score"] > 70]))
    col3.metric("Worth a look", len(scored_df[(scored_df["score"] >= 50) & (scored_df["score"] <= 70)]))
    col4.metric("Applied", len(df[df["status"] == "Applied"]))

    st.divider()

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
                    <div class="job-card-title">{job['title']}</div>
                    <div class="job-card-company">{job['company']}{network_badge}</div>
                    <div class="job-card-meta">{job['platform'].upper()} &nbsp;&middot;&nbsp; {job.get('tier', '')} &nbsp;&middot;&nbsp; Score {score_val}{_format_date_badge(job)}</div>
                </div>
                <div class="score-badge">{score_val}</div>
            </div>
        """

        details = []
        sal_min = job.get("salary_min")
        sal_max = job.get("salary_max")
        if pd.notna(sal_min) and pd.notna(sal_max) and sal_min and sal_max:
            sal_src = _safe_str(job.get("salary_source"))
            src_label = f" ({sal_src})" if sal_src else ""
            details.append(f"<strong>Salary:</strong> ${int(sal_min):,} – ${int(sal_max):,}{src_label}")
        gd = _safe_str(job.get("glassdoor_rating"))
        cf = _safe_str(job.get("culture_flags"))
        culture_parts = []
        if gd and gd.lower() != "unknown":
            culture_parts.append(f"Glassdoor {gd}")
        if cf and cf.lower() != "unknown":
            culture_parts.append(cf)
        if culture_parts:
            details.append(f"<strong>Culture:</strong> {' · '.join(culture_parts)}")
        if job.get("score_reasoning"):
            details.append(f"<strong>Fit:</strong> {job['score_reasoning']}")
        if job.get("hiring_manager_name") and job["hiring_manager_name"] != "Unknown":
            hm_title = job.get("hiring_manager_title", "")
            details.append(
                f"<strong>Reach out to:</strong> {job['hiring_manager_name']} ({hm_title})"
            )
        if job.get("company_win") and job["company_win"] != "No recent news found.":
            win_text = job["company_win"][:120]
            details.append(f"<strong>Recent:</strong> {win_text}...")

        if details:
            card_html += '<div class="job-card-detail">' + "<br>".join(details) + "</div>"

        card_html += f"""
            <div style="margin-top: 0.8rem;">
                <a class="job-card-link" href="{job['url']}" target="_blank">View posting &rarr;</a>
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
                except Exception as e:
                    st.error(f"Failed: {e}")

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
                except Exception as e:
                    st.error(f"Failed: {e}")

st.divider()

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
            f'<span class="job-card-title" style="font-size: 1.05rem;">{job["title"]}</span>'
            f'<span class="job-card-meta" style="margin-left: 0.8rem;">{job["company"]} &middot; {score_val}</span>'
            f'</div>'
            f'<a class="job-card-link" href="{job["url"]}" target="_blank">View &rarr;</a>'
            f'</div></div>',
            unsafe_allow_html=True,
        )

st.divider()

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
        "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100),
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
            name = f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip()
            position = contact.get("position", "")
            company = contact.get("company", "")
            pos_label = f" — {position}" if position else ""
            st.markdown(
                f'<div class="job-card" style="padding: 0.8rem 1.4rem;">'
                f'<span class="job-card-title" style="font-size: 1rem;">{name}</span>'
                f'<span class="job-card-meta" style="margin-left: 0.6rem;">{company}{pos_label}</span>'
                f'<br><span class="job-card-meta">Role: {job_row["title"]}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
