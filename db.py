import json, sqlite3
from datetime import datetime, timezone
from uuid import uuid4
from contextlib import closing
from pathlib import Path
ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'; DATA.mkdir(exist_ok=True)
DB=DATA/'jobs.sqlite3'

def conn():
    c=sqlite3.connect(DB)
    c.row_factory=sqlite3.Row
    c.execute('''CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, company TEXT NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL UNIQUE, location TEXT DEFAULT '', status TEXT DEFAULT 'Saved', notes TEXT DEFAULT '', answers TEXT DEFAULT '{}', created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    if 'application_details' not in {row[1] for row in c.execute('PRAGMA table_info(jobs)')}:
        c.execute("ALTER TABLE jobs ADD COLUMN application_details TEXT DEFAULT '{}'")
    c.execute('CREATE TABLE IF NOT EXISTS app_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    c.commit(); return c

def get_jobs():
    with closing(conn()) as c: return [dict(x) for x in c.execute('SELECT * FROM jobs ORDER BY id DESC')]


def queue_revision():
    with closing(conn()) as c:
        row = c.execute("SELECT value FROM app_metadata WHERE key='queue_revision'").fetchone()
        return row[0] if row else ''


def clear_job_queue():
    """Back up the exact queue inside the deletion transaction, then clear it.

    A JSON archive is independent of SQLite locks and is readable for recovery.
    Profile, documents, login sessions and public description caches are retained.
    """
    with closing(conn()) as c:
        c.execute('BEGIN IMMEDIATE')
        try:
            jobs = [dict(row) for row in c.execute('SELECT * FROM jobs ORDER BY id')]
            if not jobs:
                c.rollback()
                return 0, None
            folder = DATA / 'backups'
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            backup = folder / f'job-queue-{stamp}-{uuid4().hex[:8]}.json'
            backup.write_text(json.dumps({'created_at': datetime.now(timezone.utc).isoformat(), 'jobs': jobs}, indent=2), encoding='utf-8')
            c.execute('DELETE FROM jobs')
            c.execute("INSERT OR REPLACE INTO app_metadata(key,value) VALUES('queue_revision',?)", (uuid4().hex,))
            c.commit()
            return len(jobs), backup
        except Exception:
            c.rollback()
            raise

def get_job(job_id):
    with closing(conn()) as c:
        x=c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
        return dict(x) if x else None

def save_job(company,title,url,location=''):
    with closing(conn()) as c:
        c.execute('INSERT OR IGNORE INTO jobs(company,title,url,location) VALUES(?,?,?,?)',(company,title,url,location));c.commit()
        return c.execute('SELECT id FROM jobs WHERE url=?',(url,)).fetchone()[0]

def update_job(job_id, **fields):
    allowed={'status','notes','answers','company','title','location','application_details'}
    fields={k:v for k,v in fields.items() if k in allowed}
    if fields:
        with closing(conn()) as c:
            c.execute('UPDATE jobs SET '+','.join(f'{k}=?' for k in fields)+' WHERE id=?',(*fields.values(),job_id));c.commit()

def profile():
    p=DATA/'profile.json'; return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}

def save_profile(p):
    (DATA/'profile.json').write_text(json.dumps(p,indent=2),encoding='utf-8')
