import Database from 'better-sqlite3';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const DB_PATH = join(__dirname, 'job_tracker.db');

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

// --- Schema ---
db.exec(`
  CREATE TABLE IF NOT EXISTS jobs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    url                   TEXT UNIQUE,
    title                 TEXT,
    company               TEXT,
    platform              TEXT,
    score                 INTEGER,
    tier                  TEXT,
    status                TEXT DEFAULT 'Unexplored',
    description           TEXT,
    score_reasoning       TEXT,
    hiring_manager_name   TEXT,
    hiring_manager_title  TEXT,
    company_win           TEXT,
    vibe_check_email      TEXT,
    discovered_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at            DATETIME DEFAULT CURRENT_TIMESTAMP
  );

  CREATE TABLE IF NOT EXISTS run_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME,
    jobs_found INTEGER DEFAULT 0,
    jobs_scored INTEGER DEFAULT 0,
    jobs_enriched INTEGER DEFAULT 0
  );
`);

// --- Prepared Statements ---
// --- Migrations ---
try { db.exec(`ALTER TABLE jobs ADD COLUMN posted_at DATETIME`); } catch {}
try { db.exec(`ALTER TABLE jobs ADD COLUMN salary_min INTEGER`); } catch {}
try { db.exec(`ALTER TABLE jobs ADD COLUMN salary_max INTEGER`); } catch {}
try { db.exec(`ALTER TABLE jobs ADD COLUMN salary_source TEXT`); } catch {}
try { db.exec(`ALTER TABLE jobs ADD COLUMN glassdoor_rating TEXT`); } catch {}
try { db.exec(`ALTER TABLE jobs ADD COLUMN culture_flags TEXT`); } catch {}
try { db.exec(`ALTER TABLE jobs ADD COLUMN similar_roles TEXT`); } catch {}
try { db.exec(`ALTER TABLE jobs ADD COLUMN culture_notes TEXT`); } catch {}

// Contacts table for LinkedIn networking map
db.exec(`
  CREATE TABLE IF NOT EXISTS contacts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name    TEXT,
    last_name     TEXT,
    email         TEXT,
    company       TEXT,
    position      TEXT,
    connected_on  TEXT
  );
`);

const insertJob = db.prepare(`
  INSERT OR IGNORE INTO jobs (url, title, company, platform, description, posted_at)
  VALUES (@url, @title, @company, @platform, @description, @posted_at)
`);

const updateScore = db.prepare(`
  UPDATE jobs SET score = @score, tier = @tier, score_reasoning = @reasoning,
    updated_at = CURRENT_TIMESTAMP
  WHERE id = @id
`);

const updateEnrichment = db.prepare(`
  UPDATE jobs SET hiring_manager_name = @hiring_manager_name,
    hiring_manager_title = @hiring_manager_title,
    company_win = @company_win,
    salary_min = @salary_min,
    salary_max = @salary_max,
    salary_source = @salary_source,
    glassdoor_rating = @glassdoor_rating,
    culture_flags = @culture_flags,
    status = 'Researched',
    updated_at = CURRENT_TIMESTAMP
  WHERE id = @id
`);

const updateEmail = db.prepare(`
  UPDATE jobs SET vibe_check_email = @email, updated_at = CURRENT_TIMESTAMP
  WHERE id = @id
`);

const updateStatus = db.prepare(`
  UPDATE jobs SET status = @status, updated_at = CURRENT_TIMESTAMP
  WHERE id = @id
`);

const getUnscoredJobs = db.prepare(`SELECT * FROM jobs WHERE score IS NULL`);
const getHighScoreJobs = db.prepare(`SELECT * FROM jobs WHERE score > 70 AND hiring_manager_name IS NULL`);
const getJobsNeedingEmail = db.prepare(`SELECT * FROM jobs WHERE score > 70 AND hiring_manager_name IS NOT NULL AND vibe_check_email IS NULL`);
const getAllJobs = db.prepare(`SELECT * FROM jobs ORDER BY score DESC`);
const getJobByUrl = db.prepare(`SELECT * FROM jobs WHERE url = ?`);

const insertRun = db.prepare(`INSERT INTO run_log DEFAULT VALUES`);
const updateRun = db.prepare(`
  UPDATE run_log SET finished_at = CURRENT_TIMESTAMP,
    jobs_found = @jobs_found, jobs_scored = @jobs_scored, jobs_enriched = @jobs_enriched
  WHERE id = @id
`);

// --- Exports ---
export {
  db,
  insertJob,
  updateScore,
  updateEnrichment,
  updateEmail,
  updateStatus,
  getUnscoredJobs,
  getHighScoreJobs,
  getJobsNeedingEmail,
  getAllJobs,
  getJobByUrl,
  insertRun,
  updateRun,
};
