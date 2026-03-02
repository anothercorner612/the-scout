# The Scout — Implementation Plan

## Architecture Overview

```
hunter.js (Node.js CLI)          dashboard.py (Streamlit)
┌──────────────────────┐         ┌──────────────────────┐
│ Phase 1: DISCOVER    │         │ Scored Jobs Table     │
│ Gemini 2.5 Pro +     │         │ Hiring Manager Cards  │
│ Google Search Ground. │───────▶│ Vibe Check Emails     │
│                      │  SQLite │ Status Filters        │
│ Phase 2: SCORE       │  (DB)  │ Score Distribution    │
│ Gemini 2.5 Flash     │         └──────────────────────┘
│                      │
│ Phase 3: ENRICH      │
│ Gemini 2.5 Pro +     │
│ Google Search Ground. │
│                      │
│ Phase 4: DRAFT       │
│ Gemini 2.5 Flash     │
└──────────────────────┘
```

## Files to Create

| File | Purpose |
|------|---------|
| `package.json` | Dependencies: `@google/genai`, `dotenv`, `better-sqlite3`, `chalk`, `ora` |
| `db.js` | SQLite schema + helper functions (insert, dedupe, update status) |
| `hunter.js` | Main CLI entry point — orchestrates all 4 phases |
| `dashboard.py` | Streamlit app reading from `job_tracker.db` |
| `requirements.txt` | `streamlit`, `pandas` |

## Database Schema (`job_tracker.db`)

```sql
CREATE TABLE jobs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  url           TEXT UNIQUE,
  title         TEXT,
  company       TEXT,
  platform      TEXT,          -- greenhouse | lever | ashby
  score         INTEGER,       -- 0-100
  tier          TEXT,          -- tier1 | tier2 | no_match
  status        TEXT DEFAULT 'Unexplored',
  description   TEXT,
  score_reasoning TEXT,
  hiring_manager_name  TEXT,
  hiring_manager_title TEXT,
  company_win          TEXT,
  vibe_check_email     TEXT,
  discovered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

## Phase 1: DISCOVER (`hunter.js`)

**Model:** `gemini-2.5-pro` with `{ googleSearch: {} }` tool

Run 3 grounded search queries (one per ATS platform):

```
Search Query Template:
"site:{platform_domain} remote 'program manager' OR 'technical program manager'
OR 'creative operations' OR 'design systems' OR 'product operations'
posted within last 7 days United States"
```

Platforms:
- `boards.greenhouse.io` — Greenhouse
- `jobs.lever.co` — Lever
- `jobs.ashbyhq.com` — Ashby

**Extract URLs** from `response.candidates[0].groundingMetadata.groundingChunks[].web.uri`

**Deduplicate** against existing `jobs.url` in SQLite before proceeding.

## Phase 2: SCORE (`hunter.js`)

**Model:** `gemini-2.5-flash` (fast, cheap — no grounding needed)

For each discovered URL, send the job description text to Flash with this prompt:

```
You are a job-fit scoring engine. Score this job 0-100 against these criteria:

TIER 1 (weight 100%): {tier1 from goals.md}
TIER 2 (weight 75%): {tier2 from goals.md}
SPECIALIZED SKILLS: {keywords from goals.md}

HARD REJECT if any of these are true:
- Non-remote (on-site, hybrid, 3 days in office)
- Non-technical industry (construction, healthcare, real estate, purely admin)
- Junior/Coordinator/Associate title

Return JSON: { "score": number, "tier": "tier1"|"tier2"|"no_match", "reasoning": "2 sentences" }
```

**Implementation detail:** Since we're using grounded search results, we already have the job content from Phase 1's grounding chunks. For any jobs where we need fuller descriptions, we make a second grounded call to read the specific URL.

## Phase 3: ENRICH (score > 85 only)

**Model:** `gemini-2.5-pro` with `{ googleSearch: {} }` tool

Two grounded queries per high-scoring job:

1. **Hiring Manager Discovery:**
   ```
   "Who is the hiring manager for {role title} at {company}?
   Search LinkedIn and the company's about/team page.
   Return: name, title, LinkedIn URL if found."
   ```

2. **Company Win:**
   ```
   "What is {company}'s most notable recent achievement, funding round,
   product launch, or press mention from the last 90 days?
   Return one specific, citeable fact."
   ```

## Phase 4: DRAFT (score > 85 only)

**Model:** `gemini-2.5-flash`

Generate a 150-word "Vibe Check" email per CLAUDE.md spec:

```
Write a 150-word cold outreach email to {hiring_manager_name} ({title}) at {company}.
The role is: {job_title}.
Mention this specific company win: {company_win}.
Tone: Confident but not arrogant. Show you understand their problem space.
Do NOT use buzzwords. Do NOT start with "I hope this email finds you well."
Sign off as the user (we'll add their name later).
```

## Phase 5: CLI Output + Storage

- Save all results to `job_tracker.db`
- Print a summary table to terminal using `chalk`:
  ```
  ┌─────┬──────────────────────────────┬───────────┬───────┬────────┐
  │  #  │ Role                         │ Company   │ Score │ Status │
  ├─────┼──────────────────────────────┼───────────┼───────┼────────┤
  │  1  │ Design Systems PM            │ Stripe    │  92   │  NEW   │
  │  2  │ TPM, Developer Experience    │ Vercel    │  88   │  NEW   │
  └─────┴──────────────────────────────┴───────────┴───────┴────────┘
  ```

## `dashboard.py` (Streamlit)

Sections:
1. **Header** — "The Scout" branding + last run timestamp
2. **Score Distribution** — Bar chart of all scored jobs
3. **Hot Leads** (score > 85) — Cards showing: role, company, score, hiring manager, company win, vibe check email with copy button
4. **All Jobs** — Filterable/sortable table with status dropdown (Unexplored → Researched → Applied → Followed-Up)
5. **Sidebar** — Filter by platform, score range, tier, status

## Implementation Order

1. `package.json` + `npm install`
2. `db.js` — schema + helpers
3. `hunter.js` — Phase 1 (Discover) only, test it works
4. `hunter.js` — Phase 2 (Score), test end-to-end
5. `hunter.js` — Phase 3+4 (Enrich + Draft), test with real results
6. `requirements.txt` + `dashboard.py`
7. End-to-end test run

## Key Technical Decisions

- **`gemini_key`** from `.env` (not `GEMINI_API_KEY`) — matching your existing env var name
- **`better-sqlite3`** for Node.js SQLite — synchronous API, no callback hell, fast
- **Rate limiting** — 1-second delay between Gemini API calls to stay within free-tier limits
- **Deduplication** — `jobs.url` is UNIQUE; re-runs skip already-discovered jobs
- **US Remote filter** — baked into search queries + validated in scoring prompt
- **Error handling** — individual job failures don't kill the whole run; errors logged, processing continues
