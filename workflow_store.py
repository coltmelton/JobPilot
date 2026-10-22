"""Persistent batch inbox. Commands and screenshots are encrypted with DPAPI."""
import json
import sqlite3
import time
import uuid
from contextlib import closing

import db
from credential_vault import protect, unprotect

NEEDS_HELP = ('needs_credentials', 'login_failed', 'account_required', 'verification_required',
              'needs_information', 'review_ready', 'manual_browser')
TERMINAL = ('submitted', 'skipped', 'failed', 'stopped')


def connect():
    connection = sqlite3.connect(db.DB, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.executescript('''
        CREATE TABLE IF NOT EXISTS workflow_runs (
            id TEXT PRIMARY KEY, state TEXT, created REAL, heartbeat REAL, config TEXT);
        CREATE TABLE IF NOT EXISTS workflow_tasks (
            id TEXT PRIMARY KEY, run_id TEXT, job_id INTEGER, position INTEGER,
            state TEXT, message TEXT, updated REAL, snapshot TEXT DEFAULT '{}', screenshot BLOB);
        CREATE TABLE IF NOT EXISTS workflow_commands (
            id INTEGER PRIMARY KEY, task_id TEXT, payload BLOB);
    ''')
    return connection


def create_run(job_ids, resume='', workers=1):
    job_ids=list(dict.fromkeys(job_ids))
    if not job_ids:raise ValueError('Choose at least one job.')
    if workers!=1:raise ValueError('Background applications run one at a time.')
    # Verify DPAPI before creating any work or launching a browser.
    unprotect(protect(b'JobPilot vault check'))
    run_id = uuid.uuid4().hex
    now = time.time()
    with closing(connect()) as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT 1 FROM workflow_runs WHERE state IN ('running','stopping')").fetchone():
            raise ValueError('A batch is already active. Finish or stop it before starting another.')
        c.execute('INSERT INTO workflow_runs VALUES (?,?,?,?,?)', (run_id, 'running', now, now, json.dumps({'resume': resume, 'workers': workers})))
        for position, jid in enumerate(job_ids):
            if not db.get_job(jid):
                raise ValueError('A selected job no longer exists. Refresh your queue.')
            c.execute('INSERT INTO workflow_tasks(id,run_id,job_id,position,state,message,updated) VALUES (?,?,?,?,?,?,?)',
                      (uuid.uuid4().hex, run_id, jid, position, 'queued', 'Waiting in batch', now))
        c.commit()
    return run_id


def runs():
    with closing(connect()) as c:
        return [dict(row) for row in c.execute('SELECT * FROM workflow_runs ORDER BY created DESC LIMIT 10')]


def get_run(run_id):
    with closing(connect()) as c:
        row = c.execute('SELECT * FROM workflow_runs WHERE id=?', (run_id,)).fetchone()
        return dict(row) if row else None


def tasks(run_id):
    with closing(connect()) as c:
        return [dict(row) for row in c.execute('''SELECT t.id,t.run_id,t.job_id,t.position,t.state,t.message,t.updated,t.snapshot,
            j.company,j.title,j.url FROM workflow_tasks t LEFT JOIN jobs j ON j.id=t.job_id
            WHERE run_id=? ORDER BY position''', (run_id,))]


def get_task(task_id):
    with closing(connect()) as c:
        row = c.execute('SELECT * FROM workflow_tasks WHERE id=?', (task_id,)).fetchone()
        return dict(row) if row else None


def update_task(task_id, state, message, snapshot=None, screenshot=None):
    values = {'state': state, 'message': message, 'updated': time.time()}
    if snapshot is not None:
        values['snapshot'] = json.dumps(snapshot)
    if screenshot is not None:
        values['screenshot'] = protect(screenshot)
    with closing(connect()) as c:
        c.execute('UPDATE workflow_tasks SET '+','.join(f'{key}=?' for key in values)+' WHERE id=?', (*values.values(), task_id))
        c.commit()


def touch(run_id, task_id=None):
    with closing(connect()) as c:
        c.execute('UPDATE workflow_runs SET heartbeat=? WHERE id=?', (time.time(), run_id))
        if task_id:c.execute('UPDATE workflow_tasks SET updated=? WHERE id=?', (time.time(), task_id))
        c.commit()


def set_run_state(run_id, state):
    with closing(connect()) as c:
        c.execute('UPDATE workflow_runs SET state=?,heartbeat=? WHERE id=?', (state, time.time(), run_id))
        c.commit()


def send_command(task_id, action, view_id=None, **payload):
    encrypted = protect(json.dumps({'action': action, 'view_id': view_id, **payload}).encode('utf-8'))
    with closing(connect()) as c:
        task = c.execute('SELECT state,snapshot FROM workflow_tasks WHERE id=?', (task_id,)).fetchone()
        if not task or task['state'] in TERMINAL:
            raise ValueError('This task has finished. Refresh the inbox.')
        if view_id is not None and json.loads(task['snapshot']).get('view_id') != view_id:
            raise ValueError('The employer page changed. Refresh the inbox before sending changes.')
        c.execute('INSERT INTO workflow_commands(task_id,payload) VALUES (?,?)', (task_id, encrypted))
        c.commit()


def pop_command(task_id):
    with closing(connect()) as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM workflow_commands WHERE task_id=? ORDER BY id LIMIT 1', (task_id,)).fetchone()
        if not row:
            c.rollback();return None
        c.execute('DELETE FROM workflow_commands WHERE id=?', (row['id'],));c.commit()
    return json.loads(unprotect(bytes(row['payload'])).decode('utf-8'))


def screenshot_bytes(task_id):
    with closing(connect()) as c:
        row = c.execute('SELECT screenshot FROM workflow_tasks WHERE id=?', (task_id,)).fetchone()
    return unprotect(bytes(row[0])) if row and row[0] else None


def finish_run(run_id, state='finished'):
    with closing(connect()) as c:
        c.execute("UPDATE workflow_tasks SET state='stopped',message='Batch stopped',updated=? WHERE run_id=? AND state NOT IN ('submitted','skipped','failed','stopped')", (time.time(), run_id))
        c.execute('DELETE FROM workflow_commands WHERE task_id IN (SELECT id FROM workflow_tasks WHERE run_id=?)', (run_id,))
        c.execute('UPDATE workflow_runs SET state=?,heartbeat=? WHERE id=?', (state, time.time(), run_id));c.commit()
