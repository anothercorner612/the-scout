"""
scout.py — Python port of hunter.js pipeline.
Phases: Discover → Score → Enrich → Draft
Called directly from dashboard.py instead of subprocess.
"""

import asyncio
import json
import os
import re
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from google import genai

load_dotenv(Path(__file__).parent / ".env")

ai_client = genai.Client(api_key=os.getenv("gemini_key"))

MODELS = {
    "pro": "gemini-2.5-pro",
    "flash": "gemini-2.5-flash",
}

# --- Title / filter config (mirrors hunter.js) ---
TITLE_KEYWORDS = [
    "program manager", "technical program manager", "tpm",
    "product manager",
    "creative operations", "design systems", "product operations",
    "developer experience", "design operations", "ai operations",
    "project manager", "design program", "creative program",
    "operations manager", "digital project", "web project",
    "implementation manager", "client delivery", "solutions manager",
    "launch manager", "release manager", "delivery manager",
]

REJECT_COMPANIES = ["whatnot", "onebrief"]

REJECT_TITLES = [
    "junior", "associate", "coordinator", "intern", "entry level",
    "director", "vice president", "vp ", "vp,", "chief",
    "principal", "staff ", "distinguished",
    "design lead", "ux lead", "product designer", "ux designer",
    "visual designer", "interaction designer", "design manager",
]

REJECT_DESCRIPTION = [
    "security clearance", "top secret", "ts/sci", "must be clearable",
    "within 50 miles", "within 25 miles", "miles of the office",
    "hybrid role", "in-office requirement", "on-site required",
]

SEED_COMPANIES = [
    "webflow", "canva", "figma", "miro", "pitch", "loom",
    "contentful", "sanity", "storyblok", "hygraph", "strapi",
    "framer", "protopie", "zeplin", "maze-co", "useberry",
    "invisionapp", "abstract", "brandfolder", "bynder", "frontify",
    "vercel", "netlify", "render", "railway", "fly",
    "linear", "shortcut", "height", "clickup", "coda",
    "postman", "snyk", "sentry", "launchdarkly", "doppler",
    "retool", "airplane", "superblocks", "appsmith",
    "dbt-labs", "fivetran", "airbyte", "rudderstack",
    "supabase", "neon", "planetscale", "turso",
    "prisma", "hasura", "fauna",
    "expo", "tailwindlabs",
    "shopify", "bigcommerce", "nacelle", "swell",
    "contentstack", "ninetailed", "algolia", "bloomreach",
    "klaviyo", "attentive", "yotpo", "gorgias",
    "northbeam", "deel", "remote", "gusto", "justworks",
    "ramp", "brex", "mercury", "puzzle",
    "vanta", "drata", "secureframe",
    "lattice", "culture-amp", "leapsome",
    "calendly", "zapier", "buffer", "automattic", "ghost",
    "airtable",
    "thoughtbot", "metalab", "instrument", "work-and-co",
    "huge", "ueno", "fantasy", "phase2technology",
    "bounteous", "perficient", "slalom", "publicissapient",
    "accenture-song", "epam", "cognizant", "ideo",
    "frog", "designit", "teague", "artefact",
    "gorilla-group", "bluetext", "viget", "happycog",
    "velir", "mediacurrent", "lullabot", "four-kitchens",
    "10up", "developer", "wpengine", "pantheon",
    "perfectserve", "inductivehealth", "netsuite", "salesforce",
    "acquia", "sitecore", "episerver", "optimizely",
    "wpvip", "pantheon", "platform-sh", "kinsta",
    "grafana", "pagerduty", "cockroachlabs", "timescale",
    "sourcegraph", "gitpod", "coder", "codespaces",
    "stytch", "clerk", "workos",
    "notion", "gitlab", "asana", "monday",
    "amplitude", "mixpanel", "fullstory", "hotjar",
    "greenhouse", "lever", "ashby",
]

# Default scoring system (used when no per-user prompt exists — generic fallback)
DEFAULT_SCORING_SYSTEM = """You are a strict job-fit scoring engine. Score each job 0-100. Most jobs should score 40-70. Scores above 85 should be rare and require exceptional alignment.

CANDIDATE: Experienced professional seeking their next role. No specific profile provided — score based on general job quality signals.

SCORING RANGES — follow these carefully:
- 90-100: EXCEPTIONAL — Reserve for near-perfect matches. A 100 should almost never be given. Requires the role's core function, seniority, and industry to all align precisely.
- 80-89 (tier1): STRONG — The role's primary responsibilities clearly match the candidate's likely strengths. Not just "a PM role at a tech company."
- 65-79 (tier2): SOLID — Good company, reasonable role, but missing 1-2 key alignment factors.
- 45-64: MEDIOCRE — Right industry but wrong specialization, or right function but wrong industry. Example: a Marketing Operations role when the candidate is a Product PM.
- 20-44: WEAK — Tangential connection at best. The candidate could theoretically do it but it's not what they're looking for.
- 0: HARD REJECT — Spam, scam, or roles with major red flags.

REALISM RULES:
- Do NOT give 90+ just because a role is at a good company or has a nice title. The core day-to-day work must align.
- Roles where the primary function is marketing, legal, finance, HR, or sales should score 20-50 even if the title contains "Operations" or "Program Manager."
- Vague or generic postings with buzzwords but no substance → subtract 10.
- "Table stakes" keywords like Agile, Scrum, JIRA, cross-functional, stakeholder management appear in nearly every PM posting. They do NOT indicate special fit and should NOT boost scores.

Return ONLY a JSON array with one object per job:
[{"id":<job_id>,"score":<0-100>,"tier":"tier1"|"tier2"|"no_match","reasoning":"<1 sentence>"}]"""


# ============================================================
# Helpers
# ============================================================

def strip_html(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", html)).strip()[:1500]


def matches_role(title: str) -> bool:
    lower = title.lower()
    if any(r in lower for r in REJECT_TITLES):
        return False
    return any(kw in lower for kw in TITLE_KEYWORDS)


def is_remote_us(job: dict, platform: str) -> bool:
    if platform == "ashby":
        loc = (job.get("location") or "").lower()
        is_remote = job.get("isRemote") or job.get("workplaceType") == "Remote" or "remote" in loc
        is_us = any(x in loc for x in ["united states", "us", "usa", "remote"])
        return is_remote or is_us
    if platform == "lever":
        loc = (job.get("categories", {}).get("location") or "").lower()
        workplace = (job.get("workplaceType") or "").lower()
        return any(x in loc for x in ["remote", "united states", "us ", "usa"]) or workplace == "remote"
    if platform == "greenhouse":
        loc = (job.get("location", {}).get("name") or "").lower()
        return any(x in loc for x in ["remote", "united states", "us ", "usa", "anywhere"])
    if platform == "workable":
        loc = (job.get("location") or job.get("country") or "").lower()
        return any(x in loc for x in ["remote", "united states", "us", "usa", "anywhere"])
    return False


def description_disqualified(description: str) -> bool:
    if not description:
        return False
    lower = description.lower()
    return any(phrase in lower for phrase in REJECT_DESCRIPTION)


def extract_json(text: str):
    if not text:
        return None
    cleaned = text.replace("```json\n", "").replace("```json", "").replace("```\n", "").replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", cleaned)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    return None


# ============================================================
# ATS Scanners (async via httpx)
# ============================================================

async def _fetch_json(client: httpx.AsyncClient, url: str, timeout: float = 8.0):
    try:
        resp = await client.get(url, timeout=timeout)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


async def scan_greenhouse(client: httpx.AsyncClient, slug: str) -> list:
    data = await _fetch_json(client, f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    if not data or not data.get("jobs"):
        return []
    results = []
    for j in data["jobs"]:
        if not matches_role(j.get("title", "")) or not is_remote_us(j, "greenhouse"):
            continue
        desc = strip_html(j.get("content") or "")
        if description_disqualified(desc):
            continue
        results.append({
            "url": j.get("absolute_url") or f"https://boards.greenhouse.io/{slug}/jobs/{j.get('id', '')}",
            "title": j["title"],
            "company": j.get("company_name") or slug,
            "platform": "greenhouse",
            "description": desc,
            "posted_at": j.get("updated_at") or j.get("first_published"),
        })
    return results


async def scan_lever(client: httpx.AsyncClient, slug: str) -> list:
    data = await _fetch_json(client, f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if not isinstance(data, list):
        return []
    results = []
    for j in data:
        if not matches_role(j.get("text", "")) or not is_remote_us(j, "lever"):
            continue
        desc = j.get("descriptionPlain") or ""
        if description_disqualified(desc):
            continue
        posted = None
        if j.get("createdAt"):
            try:
                from datetime import datetime, timezone
                posted = datetime.fromtimestamp(j["createdAt"] / 1000, tz=timezone.utc).isoformat()
            except Exception:
                pass
        results.append({
            "url": j.get("hostedUrl") or f"https://jobs.lever.co/{slug}/{j.get('id', '')}",
            "title": j["text"],
            "company": slug[0].upper() + slug[1:],
            "platform": "lever",
            "description": desc,
            "posted_at": posted,
        })
    return results


async def scan_ashby(client: httpx.AsyncClient, slug: str) -> list:
    data = await _fetch_json(client, f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    if not data or not data.get("jobs"):
        return []
    results = []
    for j in data["jobs"]:
        if not matches_role(j.get("title", "")) or not is_remote_us(j, "ashby"):
            continue
        desc = j.get("descriptionPlain") or ""
        if description_disqualified(desc):
            continue
        results.append({
            "url": j.get("jobUrl") or f"https://jobs.ashbyhq.com/{slug}/{j.get('id', '')}",
            "title": j["title"],
            "company": slug[0].upper() + slug[1:],
            "platform": "ashby",
            "description": desc,
            "posted_at": j.get("publishedAt"),
        })
    return results


async def scan_workable(client: httpx.AsyncClient, slug: str) -> list:
    data = await _fetch_json(client, f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
    if not data or not data.get("jobs"):
        return []
    results = []
    for j in data["jobs"]:
        if not matches_role(j.get("title", "")) or not is_remote_us(j, "workable"):
            continue
        desc = strip_html(j.get("shortDescription") or j.get("description") or "")
        if description_disqualified(desc):
            continue
        results.append({
            "url": j.get("url") or f"https://apply.workable.com/{slug}/j/{j.get('shortcode', '')}",
            "title": j["title"],
            "company": slug[0].upper() + slug[1:],
            "platform": "workable",
            "description": desc,
            "posted_at": j.get("published"),
        })
    return results


async def scan_remote_ok(client: httpx.AsyncClient) -> list:
    data = await _fetch_json(client, "https://remoteok.com/api", timeout=15.0)
    if not isinstance(data, list):
        return []
    results = []
    for j in data[1:]:  # first element is metadata
        pos = j.get("position", "")
        if not pos or not matches_role(pos):
            continue
        desc = strip_html(j.get("description") or "")
        if description_disqualified(desc):
            continue
        results.append({
            "url": j.get("url") or f"https://remoteok.com/l/{j.get('id', '')}",
            "title": pos,
            "company": j.get("company") or "Unknown",
            "platform": "remoteok",
            "description": desc,
            "posted_at": j.get("date"),
        })
    return results


async def scan_weworkremotely(client: httpx.AsyncClient) -> list:
    data = await _fetch_json(client, "https://weworkremotely.com/remote-jobs.json", timeout=15.0)
    if not isinstance(data, list):
        return []
    results = []
    for j in data:
        title = j.get("title", "")
        if not title or not matches_role(title):
            continue
        desc = strip_html(j.get("description") or "")
        if description_disqualified(desc):
            continue
        results.append({
            "url": j.get("url") or f"https://weworkremotely.com{j.get('path', '')}",
            "title": title,
            "company": j.get("company_name") or j.get("company") or "Unknown",
            "platform": "weworkremotely",
            "description": desc,
            "posted_at": j.get("published_at") or j.get("created_at"),
        })
    return results


# ============================================================
# PHASE 1 — DISCOVER
# ============================================================

async def _scan_all_ats(slugs: list, on_progress=None) -> list:
    """Scan all ATS APIs + global feeds. Returns list of job dicts."""
    all_jobs = []
    async with httpx.AsyncClient(
        headers={"User-Agent": "TheScout/1.0"},
        follow_redirects=True,
    ) as client:
        # Global feeds first
        if on_progress:
            on_progress("Scanning RemoteOK and WeWorkRemotely global feeds...")
        global_results = await asyncio.gather(
            scan_remote_ok(client),
            scan_weworkremotely(client),
            return_exceptions=True,
        )
        for r in global_results:
            if isinstance(r, list):
                all_jobs.extend(r)

        # Per-company batches
        batch_size = 10
        for i in range(0, len(slugs), batch_size):
            batch = slugs[i : i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(slugs) + batch_size - 1) // batch_size
            if on_progress:
                on_progress(f"Scanning batch {batch_num}/{total_batches} ({len(all_jobs)} roles found)...")

            tasks = []
            for slug in batch:
                tasks.extend([
                    scan_greenhouse(client, slug),
                    scan_lever(client, slug),
                    scan_ashby(client, slug),
                    scan_workable(client, slug),
                ])
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, list):
                    all_jobs.extend(r)

    return all_jobs


def _hours_since_last_run(conn) -> float:
    """Return hours since the last completed pipeline run, or infinity if none."""
    try:
        row = conn.execute(
            "SELECT finished_at FROM run_log WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row and row[0]:
            from datetime import datetime, timezone
            finished = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
            if finished.tzinfo is None:
                finished = finished.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - finished
            return delta.total_seconds() / 3600
    except Exception:
        pass
    return float("inf")


def discover(conn, on_progress=None, skip_ai_discovery=False) -> dict:
    """Phase 1: Discover jobs from ATS APIs + Gemini grounded search.
    If skip_ai_discovery=True (or auto-detected as recent run), skips the
    expensive Gemini Pro grounded search and just scans ATS APIs with seed list."""
    api_calls = 0

    # Smart cache: skip Gemini discovery if last run was < 24 hours ago
    hours = _hours_since_last_run(conn)
    use_ai = not skip_ai_discovery and hours >= 24

    ai_companies = []
    if use_ai:
        if on_progress:
            on_progress("Asking Gemini for companies with open roles...")
        try:
            response = ai_client.models.generate_content(
                model=MODELS["pro"],
                contents="""
Search for US tech companies (under 5000 employees preferred) currently hiring for remote roles in:
- Project Manager (web, digital, SaaS implementation, platform migration)
- Program Manager, Technical Program Manager
- Creative Operations Manager, Design Systems Program Manager
- Product Operations Manager, Design Operations
- Developer Experience PM, Delivery Manager

Search THESE SPECIFIC SOURCES for company names:
- workatastartup.com (YC startup job board)
- jobs.a16z.com (Andreessen Horowitz portfolio)
- sequoiacap.com/jobs (Sequoia portfolio)
- wellfound.com (AngelList/Wellfound startup jobs)
- site:apply.workable.com project manager OR program manager remote
- site:bamboohr.com project manager OR creative operations remote
- site:pinpointhq.com project manager OR design operations remote
- site:boards.greenhouse.io project manager OR program manager remote
- site:jobs.lever.co project manager OR program manager remote
- site:wellfound.com/company project manager OR program manager remote

I need company names only (not job URLs). Focus on mid-market companies across SaaS, tech, digital agencies, eCommerce, and consultancies.
Prefer companies with 50-5000 employees over FAANG/Big Tech.
IMPORTANT: Include digital agencies and consultancies that hire Project Managers.
Return a JSON array of lowercase company name slugs:
["company1", "company2", ...]

Return 40-60 companies. Return ONLY the JSON array.
""",
                config={"tools": [{"google_search": {}}], "temperature": 0.2},
            )
            api_calls += 1
            text = response.text.replace("```json\n", "").replace("```", "").strip()
            parsed = json.loads(text)
            if isinstance(parsed, list):
                ai_companies = [c.lower().replace(" ", "-") for c in parsed]
        except Exception as e:
            if on_progress:
                on_progress(f"Gemini discovery failed ({e}), using seed list only")
    else:
        reason = "recent run" if hours < 24 else "skipped by user"
        if on_progress:
            on_progress(f"Skipping AI company discovery ({reason}) — scanning ATS with seed list...")

    # Merge + deduplicate
    all_slugs = list(set(SEED_COMPANIES + ai_companies))
    all_slugs = [s for s in all_slugs if not any(rc in s for rc in REJECT_COMPANIES)]

    if on_progress:
        on_progress(f"Scanning {len(all_slugs)} companies across 4 ATS platforms + global feeds...")

    # Run async scanners
    all_jobs = asyncio.run(_scan_all_ats(all_slugs, on_progress))

    # Deduplicate and insert
    new_count = 0
    for job in all_jobs:
        existing = conn.execute("SELECT id FROM jobs WHERE url = ?", (job["url"],)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO jobs (url, title, company, platform, description, posted_at) VALUES (?, ?, ?, ?, ?, ?)",
                (job["url"], job["title"], job["company"], job["platform"], job["description"], job.get("posted_at")),
            )
            new_count += 1
    conn.commit()

    return {"total": len(all_jobs), "new": new_count, "ai_discovery": use_ai, "api_calls": api_calls}


# ============================================================
# PHASE 2 — SCORE
# ============================================================

def score(conn, scoring_system=None, on_progress=None, max_age_days=30) -> dict:
    """Phase 2: Score unscored jobs. Skips jobs older than max_age_days.
    Returns dict with scored count and api_calls count."""
    system_prompt = scoring_system or DEFAULT_SCORING_SYSTEM
    rows = conn.execute("SELECT * FROM jobs WHERE score IS NULL").fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM jobs WHERE 1=0").description]
    unscored_all = [dict(zip(cols, r)) for r in rows]

    # Filter out stale jobs — don't waste tokens scoring old postings
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    unscored = []
    stale_count = 0
    for j in unscored_all:
        posted = j.get("posted_at")
        if posted:
            try:
                dt = datetime.fromisoformat(str(posted).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < cutoff:
                    # Mark stale jobs with score 0 so they aren't retried
                    conn.execute(
                        "UPDATE jobs SET score = 0, tier = 'stale', score_reasoning = 'Skipped — posted over 30 days ago', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (j["id"],),
                    )
                    stale_count += 1
                    continue
            except (ValueError, TypeError):
                pass  # unparseable date — score it anyway
        unscored.append(j)
    if stale_count:
        conn.commit()
        if on_progress:
            on_progress(f"Skipped {stale_count} stale job(s) older than {max_age_days} days")

    scored_count = 0
    api_calls = 0
    batch_size = 5
    desc_limit = 800

    for i in range(0, len(unscored), batch_size):
        batch = unscored[i : i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(unscored) + batch_size - 1) // batch_size
        if on_progress:
            on_progress(f"Scoring batch {batch_num}/{total_batches} ({scored_count}/{len(unscored)} done)...")

        job_list = "\n---\n".join(
            f'[ID:{j["id"]}] "{j["title"]}" at {j["company"]} ({j["platform"]})\n{(j.get("description") or "")[:desc_limit]}'
            for j in batch
        )

        try:
            response = ai_client.models.generate_content(
                model=MODELS["flash"],
                contents=f"{system_prompt}\n\nJOBS TO SCORE:\n{job_list}",
                config={"temperature": 0.1},
            )
            api_calls += 1
            results = extract_json(response.text)
            if not isinstance(results, list):
                raise ValueError("Non-array response")

            for result in results:
                s = max(0, min(100, result.get("score", 0)))
                conn.execute(
                    "UPDATE jobs SET score = ?, tier = ?, score_reasoning = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (s, result.get("tier", "no_match"), result.get("reasoning", ""), result["id"]),
                )
                scored_count += 1
        except Exception:
            # Fallback: score one by one
            for job in batch:
                try:
                    desc = (job.get("description") or "")[:desc_limit]
                    resp = ai_client.models.generate_content(
                        model=MODELS["flash"],
                        contents=f'{system_prompt}\n\nJOBS TO SCORE:\n[ID:{job["id"]}] "{job["title"]}" at {job["company"]}\n{desc}',
                        config={"temperature": 0.1},
                    )
                    api_calls += 1
                    r = extract_json(resp.text)
                    result = r[0] if isinstance(r, list) else r
                    if result and result.get("score") is not None:
                        s = max(0, min(100, result["score"]))
                        conn.execute(
                            "UPDATE jobs SET score = ?, tier = ?, score_reasoning = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (s, result.get("tier", "no_match"), result.get("reasoning", ""), job["id"]),
                        )
                        scored_count += 1
                except Exception:
                    pass
                time.sleep(1)

        conn.commit()
        time.sleep(1)

    return {"scored": scored_count, "skipped_stale": stale_count, "api_calls": api_calls}


# ============================================================
# PHASE 3 — ENRICH (shared, not per-user)
# ============================================================

def enrich(conn, on_progress=None, max_age_days=30) -> dict:
    """Phase 3: Research hiring manager, salary, culture for high-score jobs.
    Skips jobs older than max_age_days. Returns dict with counts."""
    rows = conn.execute("SELECT * FROM jobs WHERE score > 70 AND hiring_manager_name IS NULL").fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM jobs WHERE 1=0").description]
    all_hot = [dict(zip(cols, r)) for r in rows]

    # Filter out stale jobs — don't spend Pro model tokens on old postings
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    hot_jobs = []
    stale_count = 0
    for j in all_hot:
        posted = j.get("posted_at")
        if posted:
            try:
                dt = datetime.fromisoformat(str(posted).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < cutoff:
                    stale_count += 1
                    continue
            except (ValueError, TypeError):
                pass
        hot_jobs.append(j)
    if stale_count and on_progress:
        on_progress(f"Skipped {stale_count} stale job(s) — too old to enrich")

    enriched_count = 0
    api_calls = 0
    for idx, job in enumerate(hot_jobs):
        if on_progress:
            on_progress(f"Researching [{idx + 1}/{len(hot_jobs)}] {job['company']}...")

        try:
            hm_response = ai_client.models.generate_content(
                model=MODELS["pro"],
                contents=f'Who is the hiring manager or team lead for "{job["title"]}" at {job["company"]}? Search LinkedIn and the company team page. Give me their full name and title.',
                config={"tools": [{"google_search": {}}], "temperature": 0.1},
            )
            api_calls += 1
            win_response = ai_client.models.generate_content(
                model=MODELS["pro"],
                contents=f"""Research {job["company"]}:
1. What is their most notable recent achievement, funding, product launch, or press mention from the last 90 days? Give one specific fact.
2. What is their Glassdoor rating (e.g. "3.8/5")? If you can't find it, say "Unknown".
3. Any notable culture reputation — remote-friendly? Recent layoffs? Known for good/bad work-life balance? Give 2-3 short flags.""",
                config={"tools": [{"google_search": {}}], "temperature": 0.1},
            )
            api_calls += 1
            salary_response = ai_client.models.generate_content(
                model=MODELS["pro"],
                contents=f'What is the typical salary range for "{job["title"]}" at {job["company"]}? Search Glassdoor, Levels.fyi, Payscale, and the job posting itself. Give the min and max annual salary in USD and cite the source.',
                config={"tools": [{"google_search": {}}], "temperature": 0.1},
            )
            api_calls += 1

            hm_raw = hm_response.text or ""
            win_raw = win_response.text or ""
            salary_raw = salary_response.text or ""

            parse_response = ai_client.models.generate_content(
                model=MODELS["flash"],
                contents=f"""Extract structured data from these research notes.

HIRING MANAGER RESEARCH:
{hm_raw[:1000]}

COMPANY WIN / CULTURE RESEARCH:
{win_raw[:1500]}

{f"SALARY RESEARCH:\\n{salary_raw[:1000]}" if salary_raw else ""}

Return ONLY valid JSON:
{{"name":"<full name or Unknown>","title":"<job title or Unknown>","win":"<one sentence company achievement or No recent news found.>","glassdoor_rating":"<e.g. 3.8/5 or Unknown>","culture_flags":"<2-3 short comma-separated flags like Remote-friendly, Good WLB, Recent layoffs — or Unknown>","salary_min":<integer or null>,"salary_max":<integer or null>,"salary_source":"<e.g. Glassdoor, Levels.fyi, job posting, or null>"}}""",
                config={"temperature": 0.0},
            )
            api_calls += 1

            data = extract_json(parse_response.text) or {}
            conn.execute(
                """UPDATE jobs SET hiring_manager_name = ?, hiring_manager_title = ?,
                   company_win = ?, salary_min = ?, salary_max = ?, salary_source = ?,
                   glassdoor_rating = ?, culture_flags = ?,
                   status = 'Researched', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (
                    data.get("name", "Unknown"),
                    data.get("title", "Unknown"),
                    data.get("win", "No recent news found."),
                    data.get("salary_min"),
                    data.get("salary_max"),
                    data.get("salary_source"),
                    data.get("glassdoor_rating"),
                    data.get("culture_flags"),
                    job["id"],
                ),
            )
            conn.commit()
            enriched_count += 1
        except Exception:
            pass

        time.sleep(2)

    return {"enriched": enriched_count, "skipped_stale": stale_count, "api_calls": api_calls}


# ============================================================
# PHASE 4 — DRAFT VIBE CHECK EMAILS
# ============================================================

# Default email prompt template (used when no user resume is available)
DEFAULT_EMAIL_BULLETS = """- Experienced professional with a track record of delivering cross-functional projects
- Strong stakeholder management and communication skills
- Comfortable working across distributed teams and time zones"""


def draft_emails(conn, user_name="the candidate", user_bullets=None, on_progress=None) -> dict:
    """Phase 4: Draft vibe check emails for enriched high-score jobs.
    Returns dict with drafted count and api_calls."""
    bullets = user_bullets or DEFAULT_EMAIL_BULLETS

    rows = conn.execute(
        "SELECT * FROM jobs WHERE score > 70 AND hiring_manager_name IS NOT NULL AND vibe_check_email IS NULL"
    ).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM jobs WHERE 1=0").description]
    jobs = [dict(zip(cols, r)) for r in rows]

    drafted_count = 0
    api_calls = 0
    for job in jobs:
        if on_progress:
            on_progress(f"Drafting email for {job['title']} at {job['company']}...")

        desc_snippet = (job.get("description") or "")[:600]
        prompt = f"""
Write a short cold email from {user_name} to {job.get("hiring_manager_name", "Hiring Manager")} ({job.get("hiring_manager_title", "")}) about the "{job["title"]}" role at {job["company"]}.

JOB DESCRIPTION EXCERPT:
{desc_snippet}

CONTEXT ABOUT {job["company"].upper()} (use sparingly, only if it helps connect to the role):
{job.get("company_win", "")}

{user_name.upper().split()[0]}'S RELEVANT EXPERIENCE (pick the 1-2 most relevant to THIS specific role):
{bullets}

RULES — THIS IS CRITICAL:
- 100-120 words MAX. Shorter is better. Hiring managers skim.
- DO NOT congratulate them on funding, revenue, or company milestones.
- DO NOT list qualifications. Show understanding of their PROBLEM instead.
- Open with a specific observation about the ROLE or what the TEAM is probably dealing with
- One concrete example from past experience that maps directly to their situation
- Close with: "Happy to share more context — would a 15-minute call work next week?"
- Sign off: "{user_name.split()[0]}"
- Tone: Like a peer texting a friend-of-a-friend about a role. Direct, warm, zero fluff.
- NO phrases: "I'm excited", "I'm confident", "I believe", "congratulations", "impressive", "incredible", "adept", "leverage", "My experience includes"
- Do NOT include a subject line. Start directly with "Hi {{first_name}},"

Return ONLY the email body, nothing else.
"""

        try:
            response = ai_client.models.generate_content(
                model=MODELS["flash"],
                contents=prompt,
                config={"temperature": 0.7},
            )
            api_calls += 1
            conn.execute(
                "UPDATE jobs SET vibe_check_email = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (response.text.strip(), job["id"]),
            )
            conn.commit()
            drafted_count += 1
        except Exception:
            pass

        time.sleep(1)

    return {"drafted": drafted_count, "api_calls": api_calls}


# ============================================================
# ORCHESTRATOR
# ============================================================

def run_pipeline(
    conn,
    scoring_system=None,
    user_name="the candidate",
    user_bullets=None,
    on_progress=None,
    phases=None,
) -> dict:
    """Run pipeline phases. Returns summary dict with API call counts.

    phases: set of phase names to run, e.g. {"discover", "score", "enrich", "draft"}.
            None or empty = run all 4 phases (full pipeline).
    """
    run_all = not phases
    phases = phases or {"discover", "score", "enrich", "draft"}

    # Insert run log
    conn.execute("INSERT INTO run_log DEFAULT VALUES")
    conn.commit()
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    total_api_calls = 0

    # Phase 1: Discover
    discovered = {"total": 0, "new": 0, "ai_discovery": False, "api_calls": 0}
    if "discover" in phases:
        if on_progress:
            on_progress("Phase 1: Discovering roles...")
        discovered = discover(conn, on_progress)
        total_api_calls += discovered.get("api_calls", 0)

    # Phase 2: Score
    score_result = {"scored": 0, "skipped_stale": 0, "api_calls": 0}
    if "score" in phases:
        if on_progress:
            on_progress("Phase 2: Scoring fit...")
        score_result = score(conn, scoring_system, on_progress)
        total_api_calls += score_result.get("api_calls", 0)

    # Phase 3: Enrich
    enrich_result = {"enriched": 0, "skipped_stale": 0, "api_calls": 0}
    if "enrich" in phases:
        if on_progress:
            on_progress("Phase 3: Researching your best shots...")
        enrich_result = enrich(conn, on_progress)
        total_api_calls += enrich_result.get("api_calls", 0)

    # Phase 4: Draft emails
    draft_result = {"drafted": 0, "api_calls": 0}
    if "draft" in phases:
        if on_progress:
            on_progress("Phase 4: Drafting outreach...")
        draft_result = draft_emails(conn, user_name, user_bullets, on_progress)
        total_api_calls += draft_result.get("api_calls", 0)

    # Update run log (api_calls column may not exist on older schemas — handle gracefully)
    try:
        conn.execute(
            "UPDATE run_log SET finished_at = CURRENT_TIMESTAMP, jobs_found = ?, jobs_scored = ?, jobs_enriched = ?, api_calls = ? WHERE id = ?",
            (discovered["new"], score_result["scored"], enrich_result["enriched"], total_api_calls, run_id),
        )
    except Exception:
        conn.execute(
            "UPDATE run_log SET finished_at = CURRENT_TIMESTAMP, jobs_found = ?, jobs_scored = ?, jobs_enriched = ? WHERE id = ?",
            (discovered["new"], score_result["scored"], enrich_result["enriched"], run_id),
        )
    conn.commit()

    if on_progress:
        on_progress(f"Done — {total_api_calls} AI calls used this run")

    return {
        "discovered": discovered,
        "scored": score_result,
        "enriched": enrich_result,
        "drafted": draft_result,
        "api_calls": total_api_calls,
        "phases_run": list(phases),
    }
