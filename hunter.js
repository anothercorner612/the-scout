import 'dotenv/config';
import { GoogleGenAI } from '@google/genai';
import chalk from 'chalk';
import ora from 'ora';
import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import {
  insertJob, updateScore, updateEnrichment, updateEmail,
  getUnscoredJobs, getHighScoreJobs, getJobsNeedingEmail,
  getAllJobs, getJobByUrl, insertRun, updateRun,
} from './db.js';

// --- Config ---
const __dirname = dirname(fileURLToPath(import.meta.url));
const goals = readFileSync(join(__dirname, 'goals.md'), 'utf-8');

const ai = new GoogleGenAI({ apiKey: process.env.gemini_key });

const MODELS = {
  pro: 'gemini-2.5-pro',
  flash: 'gemini-2.5-flash',
};

// Keywords from goals.md — titles to match in ATS results
const TITLE_KEYWORDS = [
  'program manager', 'technical program manager', 'tpm',
  'product manager',
  'creative operations', 'design systems', 'product operations',
  'developer experience', 'design operations', 'ai operations',
  'project manager', 'design program', 'creative program',
  'operations manager', 'digital project', 'web project',
  'implementation manager', 'client delivery', 'solutions manager',
  'launch manager', 'release manager', 'delivery manager',
];

// Companies to never include (bad fit, not truly remote, clearance required, etc.)
const REJECT_COMPANIES = [
  'whatnot', 'onebrief',
];

// Hard-reject title words (filter before scoring to save API calls)
const REJECT_TITLES = [
  'junior', 'associate', 'coordinator', 'intern', 'entry level',
  'director', 'vice president', 'vp ', 'vp,', 'chief',
  'principal', 'staff ', 'distinguished',
  'design lead', 'ux lead', 'product designer', 'ux designer',
  'visual designer', 'interaction designer', 'design manager',
];

// Seed list: mid-market companies (sub-5000 employees) known to hire remote PM/TPM
// Biased toward design tools, creative-tech, agencies, and mid-stage SaaS
// We try all 3 APIs for each — 404s are fast and free
const SEED_COMPANIES = [
  // Design & Creative Tools (sweet spot for Lee's profile)
  'webflow', 'canva', 'figma', 'miro', 'pitch', 'loom',
  'contentful', 'sanity', 'storyblok', 'hygraph', 'strapi',
  'framer', 'protopie', 'zeplin', 'maze-co', 'useberry',
  'invisionapp', 'abstract', 'brandfolder', 'bynder', 'frontify',

  // Mid-Market SaaS / Developer Tools
  'vercel', 'netlify', 'render', 'railway', 'fly',
  'linear', 'shortcut', 'height', 'clickup', 'coda',
  'postman', 'snyk', 'sentry', 'launchdarkly', 'doppler',
  'retool', 'airplane', 'superblocks', 'appsmith',
  'dbt-labs', 'fivetran', 'airbyte', 'rudderstack',
  'supabase', 'neon', 'planetscale', 'turso',
  'prisma', 'hasura', 'fauna',
  'expo', 'tailwindlabs',

  // eCommerce / Digital Experience (Lee's background)
  'shopify', 'bigcommerce', 'nacelle', 'swell',
  'contentstack', 'ninetailed', 'algolia', 'bloomreach',
  'klaviyo', 'attentive', 'yotpo', 'gorgias',

  // Growth-Stage Startups (sub-2000 employees, remote-friendly)
  'northbeam', 'deel', 'remote', 'gusto', 'justworks',
  'ramp', 'brex', 'mercury', 'puzzle',
  'vanta', 'drata', 'secureframe',
  'lattice', 'culture-amp', 'leapsome', 'lattice',
  'calendly', 'zapier', 'buffer', 'automattic', 'ghost',
  'airtable',

  // Agencies, Consultancies & Services (Project Manager heavy)
  'thoughtbot', 'metalab', 'instrument', 'work-and-co',
  'huge', 'ueno', 'fantasy', 'phase2technology',
  'bounteous', 'perficient', 'slalom', 'publicissapient',
  'accenture-song', 'epam', 'cognizant', 'ideo',
  'frog', 'designit', 'teague', 'artefact',
  'gorilla-group', 'bluetext', 'viget', 'happycog',
  'velir', 'mediacurrent', 'lullabot', 'four-kitchens',
  '10up', 'developer', 'wpengine', 'pantheon',

  // Implementation & Platform Companies (Project Manager roles)
  'perfectserve', 'inductivehealth', 'netsuite', 'salesforce',
  'acquia', 'sitecore', 'episerver', 'optimizely',
  'wpvip', 'pantheon', 'platform-sh', 'kinsta',

  // Infrastructure & DevOps (Tier 2 targets)
  'grafana', 'pagerduty', 'cockroachlabs', 'timescale',
  'sourcegraph', 'gitpod', 'coder', 'codespaces',
  'stytch', 'clerk', 'workos',

  // Moderate-size tech (not FAANG, but solid)
  'notion', 'gitlab', 'asana', 'monday',
  'amplitude', 'mixpanel', 'fullstory', 'hotjar',
  'greenhouse', 'lever', 'ashby',
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Robust JSON extraction — handles grounding narrative wrapping, code fences, etc.
function extractJSON(text) {
  if (!text) return null;
  const cleaned = text.replace(/```json\n?/g, '').replace(/```\n?/g, '').trim();
  // Try direct parse first
  try { return JSON.parse(cleaned); } catch {}
  // Try to find JSON object or array within the text
  const match = cleaned.match(/(\{[\s\S]*\}|\[[\s\S]*\])/);
  if (match) {
    try { return JSON.parse(match[1]); } catch {}
  }
  return null;
}

// Hard-reject phrases in job descriptions (not just titles)
const REJECT_DESCRIPTION = [
  'security clearance', 'top secret', 'ts/sci', 'must be clearable',
  'within 50 miles', 'within 25 miles', 'miles of the office',
  'hybrid role', 'in-office requirement', 'on-site required',
];

function descriptionDisqualified(description) {
  if (!description) return false;
  const lower = description.toLowerCase();
  return REJECT_DESCRIPTION.some((phrase) => lower.includes(phrase));
}

// ============================================================
// ATS API SCANNERS
// Hit the public (no-auth) APIs for Greenhouse, Lever, Ashby
// ============================================================

async function fetchJSON(url, timeoutMs = 8000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: controller.signal });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function matchesRole(title) {
  const lower = title.toLowerCase();
  if (REJECT_TITLES.some((r) => lower.includes(r))) return false;
  return TITLE_KEYWORDS.some((kw) => lower.includes(kw));
}

function isRemoteUS(job, platform) {
  if (platform === 'ashby') {
    const loc = (job.location || '').toLowerCase();
    const isRemote = job.isRemote || job.workplaceType === 'Remote' || loc.includes('remote');
    const isUS = loc.includes('united states') || loc.includes('us') ||
      loc.includes('usa') || /\b[A-Z]{2}\b/.test(job.location || '') || loc.includes('remote');
    return isRemote || isUS;
  }
  if (platform === 'lever') {
    const loc = (job.categories?.location || '').toLowerCase();
    const workplace = (job.workplaceType || '').toLowerCase();
    return loc.includes('remote') || workplace === 'remote' ||
      loc.includes('united states') || loc.includes('us ') || loc.includes('usa');
  }
  if (platform === 'greenhouse') {
    const loc = (job.location?.name || '').toLowerCase();
    return loc.includes('remote') || loc.includes('united states') ||
      loc.includes('us ') || loc.includes('usa') || loc.includes('anywhere');
  }
  if (platform === 'workable') {
    const loc = (job.location || job.country || '').toLowerCase();
    return loc.includes('remote') || loc.includes('united states') ||
      loc.includes('us') || loc.includes('usa') || loc.includes('anywhere');
  }
  return false;
}

async function scanGreenhouse(slug) {
  const data = await fetchJSON(`https://boards-api.greenhouse.io/v1/boards/${slug}/jobs?content=true`);
  if (!data?.jobs) return [];
  return data.jobs
    .filter((j) => matchesRole(j.title) && isRemoteUS(j, 'greenhouse'))
    .map((j) => ({
      url: j.absolute_url || `https://boards.greenhouse.io/${slug}/jobs/${j.id}`,
      title: j.title,
      company: j.company_name || slug,
      platform: 'greenhouse',
      description: stripHTML(j.content || ''),
      posted_at: j.updated_at || j.first_published,
    }))
    .filter((j) => !descriptionDisqualified(j.description));
}

async function scanLever(slug) {
  const data = await fetchJSON(`https://api.lever.co/v0/postings/${slug}?mode=json`);
  if (!Array.isArray(data)) return [];
  return data
    .filter((j) => matchesRole(j.text) && isRemoteUS(j, 'lever'))
    .map((j) => ({
      url: j.hostedUrl || `https://jobs.lever.co/${slug}/${j.id}`,
      title: j.text,
      company: slug.charAt(0).toUpperCase() + slug.slice(1),
      platform: 'lever',
      description: j.descriptionPlain || '',
      posted_at: j.createdAt ? new Date(j.createdAt).toISOString() : null,
    }))
    .filter((j) => !descriptionDisqualified(j.description));
}

async function scanAshby(slug) {
  const data = await fetchJSON(`https://api.ashbyhq.com/posting-api/job-board/${slug}`);
  if (!data?.jobs) return [];
  return data.jobs
    .filter((j) => matchesRole(j.title) && isRemoteUS(j, 'ashby'))
    .map((j) => ({
      url: j.jobUrl || `https://jobs.ashbyhq.com/${slug}/${j.id}`,
      title: j.title,
      company: slug.charAt(0).toUpperCase() + slug.slice(1),
      platform: 'ashby',
      description: j.descriptionPlain || '',
      posted_at: j.publishedAt || null,
    }))
    .filter((j) => !descriptionDisqualified(j.description));
}

async function scanWorkable(slug) {
  const data = await fetchJSON(`https://apply.workable.com/api/v1/widget/accounts/${slug}`);
  if (!data?.jobs) return [];
  return data.jobs
    .filter((j) => matchesRole(j.title) && isRemoteUS(j, 'workable'))
    .map((j) => ({
      url: j.url || `https://apply.workable.com/${slug}/j/${j.shortcode || ''}`,
      title: j.title,
      company: slug.charAt(0).toUpperCase() + slug.slice(1),
      platform: 'workable',
      description: stripHTML(j.shortDescription || j.description || ''),
      posted_at: j.published || null,
    }))
    .filter((j) => !descriptionDisqualified(j.description));
}

async function scanRemoteOK() {
  const data = await fetchJSON('https://remoteok.com/api', 15000);
  if (!Array.isArray(data)) return [];
  // First element is metadata — skip it
  return data.slice(1)
    .filter((j) => j.position && matchesRole(j.position))
    .map((j) => ({
      url: j.url || `https://remoteok.com/l/${j.id || ''}`,
      title: j.position,
      company: j.company || 'Unknown',
      platform: 'remoteok',
      description: stripHTML(j.description || ''),
      posted_at: j.date || null,
    }))
    .filter((j) => !descriptionDisqualified(j.description));
}

async function scanWeWorkRemotely() {
  const data = await fetchJSON('https://weworkremotely.com/remote-jobs.json', 15000);
  if (!Array.isArray(data)) return [];
  return data
    .filter((j) => j.title && matchesRole(j.title))
    .map((j) => ({
      url: j.url || `https://weworkremotely.com${j.path || ''}`,
      title: j.title,
      company: j.company_name || j.company || 'Unknown',
      platform: 'weworkremotely',
      description: stripHTML(j.description || ''),
      posted_at: j.published_at || j.created_at || null,
    }))
    .filter((j) => !descriptionDisqualified(j.description));
}

function stripHTML(html) {
  return html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim().substring(0, 1500);
}



// ============================================================
// PHASE 1 — DISCOVER
// Step A: Use Gemini to find more companies hiring these roles
// Step B: Scan all companies via ATS APIs
// ============================================================
async function discover(spinner) {
  // Step A: Ask Gemini for additional companies
  spinner.text = 'Phase 1a: Asking Gemini for companies hiring remote PM/TPM roles...';

  let aiCompanies = [];
  try {
    const response = await ai.models.generateContent({
      model: MODELS.pro,
      contents: `
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

I need company names only (not job URLs). Focus on mid-market SaaS, design tools, creative-tech, developer tools, eCommerce platforms, digital agencies, and tech consultancies.
Prefer companies with 50-5000 employees over FAANG/Big Tech.
IMPORTANT: Include digital agencies and consultancies that hire Project Managers (e.g. Bounteous, Perficient, Viget, 10up, Acquia, Sitecore, Optimizely).
Return a JSON array of lowercase company name slugs (as they'd appear in a URL, e.g. "webflow", "viget", "contentful"):
["company1", "company2", ...]

Return 40-60 companies. Include emerging and mid-stage companies, not just well-known ones. Return ONLY the JSON array.
`,
      config: {
        tools: [{ googleSearch: {} }],
        temperature: 0.2,
      },
    });

    const text = response.text.replace(/```json\n?/g, '').replace(/```\n?/g, '').trim();
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed)) {
      aiCompanies = parsed.map((c) => c.toLowerCase().replace(/\s+/g, '-'));
    }
    spinner.text = `Phase 1a: Gemini suggested ${chalk.cyan(aiCompanies.length)} companies`;
  } catch (err) {
    spinner.text = `Phase 1a: Gemini discovery failed (${err.message}), using seed list only`;
  }

  // Merge seed + AI-discovered companies (deduplicate, remove blocked)
  const allSlugs = [...new Set([...SEED_COMPANIES, ...aiCompanies])]
    .filter((slug) => !REJECT_COMPANIES.some((rc) => slug.includes(rc)));
  spinner.text = `Phase 1b: Scanning ${chalk.cyan(allSlugs.length)} companies across 4 ATS platforms + global feeds...`;

  // Step B: Scan global job feeds first (not per-company)
  const allJobs = [];

  spinner.text = 'Phase 1b: Scanning RemoteOK and WeWorkRemotely global feeds...';
  const [remoteOKJobs, wwrJobs] = await Promise.all([
    scanRemoteOK().catch(() => []),
    scanWeWorkRemotely().catch(() => []),
  ]);
  allJobs.push(...remoteOKJobs, ...wwrJobs);
  spinner.text = `Phase 1b: Global feeds found ${chalk.cyan(allJobs.length)} roles. Scanning company ATS boards...`;

  // Step C: Scan per-company ATS APIs in parallel batches
  const BATCH_SIZE = 10; // 10 companies × 4 APIs = 40 concurrent requests

  for (let i = 0; i < allSlugs.length; i += BATCH_SIZE) {
    const batch = allSlugs.slice(i, i + BATCH_SIZE);
    const batchNum = Math.floor(i / BATCH_SIZE) + 1;
    const totalBatches = Math.ceil(allSlugs.length / BATCH_SIZE);
    spinner.text = `Phase 1b: Scanning batch ${batchNum}/${totalBatches} (${allJobs.length} roles found)...`;

    const promises = batch.flatMap((slug) => [
      scanGreenhouse(slug).catch(() => []),
      scanLever(slug).catch(() => []),
      scanAshby(slug).catch(() => []),
      scanWorkable(slug).catch(() => []),
    ]);

    const results = await Promise.all(promises);
    for (const jobs of results) {
      allJobs.push(...jobs);
    }
  }

  // Deduplicate and insert into DB
  let newCount = 0;
  for (const job of allJobs) {
    const existing = getJobByUrl.get(job.url);
    if (!existing) {
      insertJob.run({
        url: job.url,
        title: job.title,
        company: job.company,
        platform: job.platform,
        description: job.description,
        posted_at: job.posted_at || null,
      });
      newCount++;
    }
  }

  return { total: allJobs.length, new: newCount };
}

// ============================================================
// PHASE 2 — SCORE (Batched)
// Uses Gemini 2.5 Flash to score jobs in batches of 5
// ============================================================
const SCORE_BATCH_SIZE = 5;
const DESC_LIMIT = 800; // chars per job description — first 800 has title/team/reqs

const SCORING_SYSTEM = `You are a job-fit scoring engine. Score each job 0-100.

CANDIDATE: 10+ yr PM bridging Engineering↔Design↔Executive teams. Strongest at: managing cross-functional technical+creative teams, large-scale migrations/rebrands, stakeholder governance. Recent: Program Manager at ResMed (global rebrand, 15+ regions), Senior PM at Think Company (50+ site migration). Tools: JIRA, Linear, Notion, Figma, GitHub, Sanity.io, SFCC. Has personal/side-project AI experience (LLM workflows, automation) — NOT a dedicated AI specialist.

TIER 1 (base 80-95): Design/Creative Operations PM, Design Systems PM, Technical PM managing creative+eng teams, Product Operations. Cross-functional Eng↔Design dependencies. Brand↔technical execution.
TIER 2 (base 65-80): TPM, DevEx PM, Product Ops, Program Manager at SaaS companies. SDLC optimization, API integrations.
BONUS KEYWORDS (+5 each, cap 95): CI/CD for Design, Token-to-Code, Git workflows, capacity planning, OKR tracking, site migration, replatforming.

REALISM MODIFIERS — APPLY THESE AFTER BASE SCORE:
- Title says Director, VP, Head of, Staff, Principal → subtract 20 (candidate is Senior/Lead level, not exec)
- Role requires 5+ years dedicated AI/ML research or PhD → subtract 25 (candidate has PM-level AI, not research)
- Company is FAANG/Big Tech (Google, Meta, Apple, Amazon, Microsoft, Netflix) → subtract 15 (ultra-competitive, low ROI)
- Role says "Senior" PM/TPM at mid-market company → no penalty (good fit)
- Role says "Manager" or "Lead" (IC not people-manager) → no penalty
- Company has <5000 employees and role matches skills → add 5 (sweet spot)

HARD REJECT (score=0): Non-remote, non-tech industry, Junior/Coordinator/Associate/Intern title, requires active security clearance.

Return ONLY a JSON array with one object per job:
[{"id":<job_id>,"score":<0-100>,"tier":"tier1"|"tier2"|"no_match","reasoning":"<1 sentence>"}]`;

async function score(spinner) {
  const unscoredJobs = getUnscoredJobs.all();
  let scored = 0;
  const totalBatches = Math.ceil(unscoredJobs.length / SCORE_BATCH_SIZE);

  for (let i = 0; i < unscoredJobs.length; i += SCORE_BATCH_SIZE) {
    const batch = unscoredJobs.slice(i, i + SCORE_BATCH_SIZE);
    const batchNum = Math.floor(i / SCORE_BATCH_SIZE) + 1;
    spinner.text = `Scoring batch ${batchNum}/${totalBatches} (${scored}/${unscoredJobs.length} done)...`;

    const jobList = batch.map((j) => {
      const desc = (j.description || '').substring(0, DESC_LIMIT);
      return `[ID:${j.id}] "${j.title}" at ${j.company} (${j.platform})\n${desc}`;
    }).join('\n---\n');

    try {
      const response = await ai.models.generateContent({
        model: MODELS.flash,
        contents: `${SCORING_SYSTEM}\n\nJOBS TO SCORE:\n${jobList}`,
        config: { temperature: 0.1 },
      });

      const results = extractJSON(response.text);
      if (!Array.isArray(results)) throw new Error('Non-array response');

      for (const result of results) {
        updateScore.run({
          id: result.id,
          score: Math.min(100, Math.max(0, result.score)),
          tier: result.tier || 'no_match',
          reasoning: result.reasoning || '',
        });
        scored++;
      }
    } catch (err) {
      // Fallback: score this batch one-by-one
      for (const job of batch) {
        try {
          const desc = (job.description || '').substring(0, DESC_LIMIT);
          const resp = await ai.models.generateContent({
            model: MODELS.flash,
            contents: `${SCORING_SYSTEM}\n\nJOBS TO SCORE:\n[ID:${job.id}] "${job.title}" at ${job.company}\n${desc}`,
            config: { temperature: 0.1 },
          });
          const r = extractJSON(resp.text);
          const result = Array.isArray(r) ? r[0] : r;
          if (result?.score != null) {
            updateScore.run({
              id: job.id,
              score: Math.min(100, Math.max(0, result.score)),
              tier: result.tier || 'no_match',
              reasoning: result.reasoning || '',
            });
            scored++;
          }
        } catch { /* skip */ }
        await sleep(1000);
      }
    }

    await sleep(1000);
  }

  return scored;
}

// ============================================================
// PHASE 3 — ENRICH (score > 85 only)
// Step 1: Gemini Pro + grounding fetches raw info (free-text OK)
// Step 2: Flash extracts structured data from the raw text
// ============================================================
async function enrich(spinner) {
  const hotJobs = getHighScoreJobs.all();
  let enriched = 0;

  for (const job of hotJobs) {
    spinner.text = `Researching [${enriched + 1}/${hotJobs.length}] ${chalk.magenta(job.company)}...`;

    try {
      // Step 1: Grounded search — let Pro return whatever format it wants
      const [hmResponse, winResponse, salaryResponse] = await Promise.all([
        ai.models.generateContent({
          model: MODELS.pro,
          contents: `Who is the hiring manager or team lead for "${job.title}" at ${job.company}? Search LinkedIn and the company team page. Give me their full name and title.`,
          config: { tools: [{ googleSearch: {} }], temperature: 0.1 },
        }),
        ai.models.generateContent({
          model: MODELS.pro,
          contents: `Research ${job.company}:
1. What is their most notable recent achievement, funding, product launch, or press mention from the last 90 days? Give one specific fact.
2. What is their Glassdoor rating (e.g. "3.8/5")? If you can't find it, say "Unknown".
3. Any notable culture reputation — remote-friendly? Recent layoffs? Known for good/bad work-life balance? Give 2-3 short flags.`,
          config: { tools: [{ googleSearch: {} }], temperature: 0.1 },
        }),
        ai.models.generateContent({
          model: MODELS.pro,
          contents: `What is the typical salary range for "${job.title}" at ${job.company}? Search Glassdoor, Levels.fyi, Payscale, and the job posting itself. Give the min and max annual salary in USD and cite the source.`,
          config: { tools: [{ googleSearch: {} }], temperature: 0.1 },
        }),
      ]);

      const hmRaw = hmResponse.text || '';
      const winRaw = winResponse.text || '';
      const salaryRaw = salaryResponse.text || '';

      // Step 2: Flash parses the free-text into structured JSON (cheap + fast)
      const parseResponse = await ai.models.generateContent({
        model: MODELS.flash,
        contents: `Extract structured data from these research notes.

HIRING MANAGER RESEARCH:
${hmRaw.substring(0, 1000)}

COMPANY WIN / CULTURE RESEARCH:
${winRaw.substring(0, 1500)}

${salaryRaw ? `SALARY RESEARCH:\n${salaryRaw.substring(0, 1000)}` : ''}

Return ONLY valid JSON:
{"name":"<full name or Unknown>","title":"<job title or Unknown>","win":"<one sentence company achievement or No recent news found.>","glassdoor_rating":"<e.g. 3.8/5 or Unknown>","culture_flags":"<2-3 short comma-separated flags like Remote-friendly, Good WLB, Recent layoffs — or Unknown>","salary_min":<integer or null>,"salary_max":<integer or null>,"salary_source":"<e.g. Glassdoor, Levels.fyi, job posting, or null>"}`,
        config: { temperature: 0.0 },
      });

      const data = extractJSON(parseResponse.text) || {};

      updateEnrichment.run({
        id: job.id,
        hiring_manager_name: data.name || 'Unknown',
        hiring_manager_title: data.title || 'Unknown',
        company_win: data.win || 'No recent news found.',
        salary_min: data.salary_min || null,
        salary_max: data.salary_max || null,
        salary_source: data.salary_source || null,
        glassdoor_rating: data.glassdoor_rating || null,
        culture_flags: data.culture_flags || null,
      });

      enriched++;
    } catch (err) {
      spinner.warn(`  Failed to enrich ${job.company}: ${err.message}`);
      spinner.start();
    }

    await sleep(2000);
  }

  return enriched;
}

// ============================================================
// PHASE 4 — DRAFT VIBE CHECK EMAILS (score > 85 + enriched)
// Uses Gemini 2.5 Flash
// ============================================================
async function draftEmails(spinner) {
  const jobs = getJobsNeedingEmail.all();
  let drafted = 0;

  for (const job of jobs) {
    spinner.text = `Drafting email for ${chalk.yellow(job.title)} at ${chalk.magenta(job.company)}...`;

    const descSnippet = (job.description || '').substring(0, 600);

    const prompt = `
Write a short cold email from Lee Frank to ${job.hiring_manager_name} (${job.hiring_manager_title}) about the "${job.title}" role at ${job.company}.

JOB DESCRIPTION EXCERPT:
${descSnippet}

CONTEXT ABOUT ${job.company.toUpperCase()} (use sparingly, only if it helps connect to the role):
${job.company_win}

LEE'S RELEVANT EXPERIENCE (pick the 1-2 most relevant to THIS specific role):
- Led a global rebrand across 15+ regions at ResMed — coordinated Eng, Design, and regional stakeholders to ship a unified system on time
- Ran a 50+ site migration for a global pharmaceutical company — zero downtime, full executive alignment through high-risk phases
- Built AI/LLM-driven workflows and a headless eCommerce platform with Sanity.io — not just managed it, actually architected it
- Scaled offshore/onshore dev cycles across 3 time zones, increased sprint velocity 25% through better QA/Dev handoffs
- Co-owns a design shop — understands the craft side, not just the process side

RULES — THIS IS CRITICAL:
- 100-120 words MAX. Shorter is better. Hiring managers skim.
- DO NOT congratulate them on funding, revenue, or company milestones. That's what every cold emailer does.
- DO NOT list qualifications. Show understanding of their PROBLEM instead.
- Open with a specific observation about the ROLE or what the TEAM is probably dealing with — show you've read the job description and understand the pain point
- One concrete example from Lee's past that maps directly to their situation (not a resume dump)
- Close with: "Happy to share more context — would a 15-minute call work next week?"
- Sign off: "Lee"
- Tone: Like a peer texting a friend-of-a-friend about a role. Direct, warm, zero fluff.
- NO phrases: "I'm excited", "I'm confident", "I believe", "congratulations", "impressive", "incredible", "adept", "leverage", "My experience includes"
- Do NOT include a subject line. Start directly with "Hi {first_name},"

Return ONLY the email body, nothing else.
`;

    try {
      const response = await ai.models.generateContent({
        model: MODELS.flash,
        contents: prompt,
        config: { temperature: 0.7 },
      });

      updateEmail.run({ id: job.id, email: response.text.trim() });
      drafted++;
    } catch (err) {
      spinner.warn(`  Failed to draft email for ${job.company}: ${err.message}`);
      spinner.start();
    }

    await sleep(1000);
  }

  return drafted;
}

// ============================================================
// MAIN — Run The Scout
// ============================================================
async function main() {
  const TERRACOTTA = chalk.hex('#C4653A');
  const WARM = chalk.hex('#5A554E');
  const MUTED = chalk.hex('#9C9488');

  console.log();
  console.log(TERRACOTTA.bold('  the scout'));
  console.log(MUTED('  your creative-tech job hunter'));
  console.log(MUTED('  ' + '~'.repeat(38)));
  console.log();

  const run = insertRun.run();
  const runId = run.lastInsertRowid;

  // Phase 1: Discover
  const discoverSpinner = ora({ text: 'Scouting roles...', color: 'yellow' }).start();
  const discovered = await discover(discoverSpinner);
  discoverSpinner.succeed(
    WARM(`Found ${TERRACOTTA.bold(discovered.total)} roles (${TERRACOTTA.bold(discovered.new)} new)`)
  );

  // Phase 2: Score
  const scoreSpinner = ora({ text: 'Scoring fit...', color: 'yellow' }).start();
  const scored = await score(scoreSpinner);
  scoreSpinner.succeed(WARM(`Scored ${TERRACOTTA.bold(scored)} roles`));

  // Phase 3: Enrich
  const enrichSpinner = ora({ text: 'Researching your best shots...', color: 'yellow' }).start();
  const enriched = await enrich(enrichSpinner);
  enrichSpinner.succeed(WARM(`Researched ${TERRACOTTA.bold(enriched)} leads`));

  // Phase 4: Draft
  const emailSpinner = ora({ text: 'Drafting outreach...', color: 'yellow' }).start();
  const drafted = await draftEmails(emailSpinner);
  emailSpinner.succeed(WARM(`Drafted ${TERRACOTTA.bold(drafted)} emails`));

  // Update run log
  updateRun.run({
    id: runId,
    jobs_found: discovered.new,
    jobs_scored: scored,
    jobs_enriched: enriched,
  });

  // Summary
  console.log();
  console.log(MUTED('  ' + '~'.repeat(38)));
  console.log();

  const allJobs = getAllJobs.all();
  const hotLeads = allJobs.filter((j) => j.score > 70);
  const warmLeads = allJobs.filter((j) => j.score >= 50 && j.score <= 70);

  if (hotLeads.length > 0) {
    console.log(TERRACOTTA.bold(`  Your best shots (${hotLeads.length})\n`));
    for (const job of hotLeads) {
      console.log(`  ${TERRACOTTA('~')} ${chalk.bold(job.title)}`);
      console.log(`    ${TERRACOTTA(job.company)} ${MUTED('/' + job.platform + ' / ' + job.score)}`);
      if (job.hiring_manager_name && job.hiring_manager_name !== 'Unknown') {
        console.log(`    ${WARM('reach out to')} ${chalk.bold(job.hiring_manager_name)} ${MUTED('(' + job.hiring_manager_title + ')')}`);
      }
      if (job.company_win && job.company_win !== 'No recent news found.') {
        console.log(`    ${MUTED(job.company_win.substring(0, 80))}...`);
      }
      console.log(`    ${MUTED(job.url)}`);
      console.log();
    }
  }

  if (warmLeads.length > 0) {
    console.log(WARM(`\n  Worth a look (${warmLeads.length})\n`));
    for (const job of warmLeads) {
      console.log(`  ${MUTED('~')} ${job.title} ${MUTED('at')} ${TERRACOTTA(job.company)} ${MUTED('/' + job.score)}`);
    }
  }

  const coldCount = allJobs.filter((j) => j.score !== null && j.score < 50).length;
  if (coldCount > 0) {
    console.log(MUTED(`\n  ${coldCount} roles didn't make the cut.`));
  }

  console.log();
  console.log(MUTED('  ' + '~'.repeat(38)));
  console.log(MUTED('  npm run dashboard to browse everything\n'));
}

main().catch((err) => {
  console.error(chalk.red(`\nFatal error: ${err.message}`));
  process.exit(1);
});
