"""Headless application preparation with a persistent human-assistance inbox."""
import hashlib
import json
import re
import time
from urllib.parse import urlsplit

import db
import workflow_store as store
from form_intelligence import fill_supported, next_step, blocking_fields, remember_answers, review_page
from browser_sessions import session_lock
from credential_vault import get_credentials, load_browser_state, save_browser_state
from workflow_browser import (capture, preview, page_state, action_named, click_action,
                              apply_changes, autofill_login)


MESSAGES = {
    'needs_credentials': 'Login required. Save or approve credentials below, or enter this page’s fields here.',
    'login_failed': 'Login did not complete. Check your credentials, use the employer’s account-creation action, or complete additional verification.',
    'account_required': 'The employer needs an account or reports that none exists. Use the Create account/Register action below, then complete the fields here.',
    'verification_required': 'Verification or a one-time code needs your help. Enter a visible code field here. Interactive CAPTCHA may require the optional manual browser.',
    'needs_information': 'This page needs additional information or an unsupported control. Complete it below, then continue.',
    'review_ready': 'Ready for your final review. Inspect the preview and fields; submission only happens when you explicitly click the employer’s Submit action below.',
    'manual_browser': 'A manual browser was opened at your request. Complete verification there, then click Resume automation here. Later jobs still run in the background.',
}


def progress_signature(page, view):
    headings = page.locator('h1,h2,[role="heading"]').all_text_contents()
    shape = [(f['frame'], f['label'], f['type'], f['required'], f['populated']) for f in view['fields']]
    return hashlib.sha256(json.dumps([page.url, headings, shape, [a['label'] for a in view['actions']]]).encode()).hexdigest()


def login_stage(page, view):
    return (page.url, tuple((f['label'], f['type']) for f in view['fields'] if not f['disabled']))


def run_task(task, resume=''):
    from playwright.sync_api import sync_playwright
    task_id, run_id = task['id'], task['run_id']
    job = db.get_job(task['job_id'])
    if not job:
        store.update_task(task_id, 'failed', 'Job was removed from the queue.');return
    if job['status'] == 'Applied':
        store.update_task(task_id, 'skipped', 'Already marked Applied; skipped to avoid applying twice.');return
    store.update_task(task_id, 'running', 'Opening the employer application in the background.')
    try:
        with session_lock(job['url']), sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(storage_state=load_browser_state(job['url']), viewport={'width':1280,'height':900})
            page = context.new_page()
            attempted_login = None
            submission_attempted = False
            paused = False
            steps = 0
            visited = {}
            view = None
            current_state = 'running'

            def current_page():
                nonlocal page
                live = [p for p in context.pages if not p.is_closed()]
                if not live:raise RuntimeError('Browser closed')
                page = live[-1]
                return page

            def publish(state, message=None):
                nonlocal view, current_state
                page = current_page()
                view = capture(page)
                try:image = preview(page)
                except Exception:image = b''
                current_state = state
                store.update_task(task_id, state, message or MESSAGES.get(state, state), snapshot=view, screenshot=image)
                save_browser_state(context, job['url'])

            try:
                for attempt in range(2):
                    try:
                        page.goto(job['url'], wait_until='domcontentloaded', timeout=30000)
                        break
                    except Exception:
                        if attempt or store.get_run(run_id)['state'] != 'running':raise
                        store.touch(run_id,task_id)
                        page.wait_for_timeout(1000)
                page.wait_for_timeout(1000)
                while browser.is_connected():
                    run = store.get_run(run_id)
                    if not run or run['state'] != 'running':
                        store.update_task(task_id, 'stopped', 'Stopped by you.');break
                    store.touch(run_id, task_id)
                    page = current_page()
                    command = store.pop_command(task_id)
                    if command:
                        action = command['action']
                        if action == 'skip':
                            db.update_job(job['id'], status='Needs review')
                            store.update_task(task_id, 'skipped', 'Skipped by you; application not marked submitted.');break
                        if command.get('view_id') is not None and (not view or command['view_id'] != view['view_id']):
                            publish(current_state, 'This request used an old page view. Review the refreshed form and try again.');continue
                        try:
                            if action == 'refresh':
                                publish(current_state);continue
                            if action == 'open_browser':
                                target = page.url
                                state = context.storage_state(indexed_db=True)
                                save_browser_state(context, job['url'])
                                browser.close()
                                browser = pw.chromium.launch(headless=False)
                                context = browser.new_context(storage_state=state, viewport={'width':1280,'height':900})
                                page = context.new_page()
                                page.goto(target, wait_until='domcontentloaded', timeout=45000)
                                publish('manual_browser');paused=True;continue
                            if action == 'fields':
                                apply_changes(page, view, command.get('changes', {}), db.DATA/'documents')
                                if command.get('remember'):remember_answers(view,command.get('changes', {}))
                                # Complete routine pages immediately after receiving the missing answer.
                                if current_state == 'needs_information':
                                    paused=False;visited.clear();steps=0
                                else:
                                    publish(current_state, 'Your entries were sent to the employer page. Choose an employer action or Resume automation.');continue
                            if action == 'act':
                                selected = next((a for a in view['actions'] if a['id'] == command.get('action_id')), None)
                                if not selected:raise ValueError('Action changed')
                                # Every submit-like action here originates from a specific user click.
                                submission_attempted = submission_attempted or bool(re.search(r'submit|send application|finish',selected['label'],re.I) or re.fullmatch(r'apply(?: now)?',selected['label'],re.I) and (view['fields'] or current_state=='review_ready'))
                                click_action(page, view, selected['id'])
                                if re.fullmatch(r'sign\s*in|log\s*in|login', selected['label'], re.I):attempted_login=login_stage(page,view)
                                page.wait_for_timeout(1200)
                            elif action == 'retry_login':
                                attempted_login=None
                            elif action not in ('resume','fields'):
                                raise ValueError('Unsupported command')
                            paused=False;visited.clear();steps=0
                        except Exception:
                            publish('needs_information', 'The employer page changed or could not accept that action. Review the refreshed controls and retry.');paused=True;continue
                    if paused:
                        page.wait_for_timeout(1000);continue
                    if steps >= 40:
                        publish('needs_information', 'Automatic step limit reached. Review this page before continuing.');paused=True;continue
                    steps += 1
                    view = capture(page)
                    if urlsplit(page.url).scheme!='https':
                        publish('needs_information','The employer navigation left HTTPS. Use an official secure application URL; no automatic personal-data filling was performed.');paused=True;continue
                    state = page_state(page, view)
                    if state == 'submitted':
                        if submission_attempted:
                            db.update_job(job['id'], status='Applied')
                            publish('submitted', 'Employer confirmation detected after your action. Application marked Applied.');break
                        publish('review_ready', 'This page appears to contain a submission confirmation. Verify it yourself; JobPilot has not marked this application Applied.');paused=True;continue
                    if state in ('account_required', 'verification_required'):
                        publish(state);paused=True;continue
                    if state == 'login':
                        stage = login_stage(page,view)
                        if attempted_login == stage:
                            publish('login_failed');paused=True;continue
                        credentials = get_credentials(page.url)
                        if not credentials:
                            publish('needs_credentials');paused=True;continue
                        attempted_login=stage
                        store.update_task(task_id, 'running', 'Attempting sign-in with the credentials approved for this portal.')
                        if autofill_login(page, view, credentials):
                            page.wait_for_timeout(1200);continue
                        publish('login_failed');paused=True;continue
                    db.update_job(job['id'], status='In progress')
                    applicant = db.profile()
                    current_job = db.get_job(job['id'])
                    filled = fill_supported(page,applicant,json.loads(current_job['answers']),resume,db.DATA/'documents')
                    view = capture(page)
                    final = action_named(view, r'submit(?: application)?|send application|finish(?: application)?|review and submit')
                    if final or review_page(page):
                        publish('review_ready');paused=True;continue
                    missing = blocking_fields(view)
                    if missing:
                        # Dependent country/state widgets often appear only after blur.
                        page.wait_for_timeout(700)
                        filled += fill_supported(page,applicant,json.loads(current_job['answers']),resume,db.DATA/'documents')
                        view=capture(page);missing=blocking_fields(view)
                    if missing:
                        labels=', '.join(dict.fromkeys(f['label'] for f in missing))
                        publish('needs_information', f'Filled {len(filled)} supported field(s). Still needs your answer: {labels[:400]}. Send these entries here; routine steps then resume automatically.');paused=True;continue
                    button = next_step(view)
                    signature = progress_signature(page, view)
                    if not button:
                        attempts=visited.get(signature,0)
                        if attempts<2:
                            visited[signature]=attempts+1;page.wait_for_timeout(1500);continue
                        publish('needs_information', 'No supported next step appeared after waiting for the page. Choose an employer action below.');paused=True;continue
                    if visited.get(signature,0)>=2:
                        reason='The employer reports a validation error. Check the page preview.' if view.get('error_count') else 'The employer did not advance after two attempts.'
                        publish('needs_information', reason+' Review the current answers and choose an employer action below.');paused=True;continue
                    visited[signature]=visited.get(signature,0)+1
                    store.update_task(task_id, 'running', 'Filling available answers and advancing to the next supported application step.')
                    try:click_action(page, view, button['id'])
                    except Exception:
                        page.wait_for_timeout(1000);continue
                    page.wait_for_timeout(1000)
            finally:
                try:save_browser_state(context, job['url'])
                except Exception:pass
                browser.close()
    except Exception as exc:
        # Do not put Playwright exception payloads into logs/status: they can contain input values.
        message = 'This portal already has a JobPilot browser open. Close it and retry this job.' if 'already has an open' in str(exc) else 'Browser preparation failed. Check connectivity, rerun setup.cmd if necessary, and retry this job.'
        store.update_task(task_id, 'failed', message)


def run_batch(run_id):
    run = store.get_run(run_id)
    if not run:raise ValueError('Unknown batch')
    resume = json.loads(run['config']).get('resume', '')
    try:
        for task in store.tasks(run_id):
            if store.get_run(run_id)['state'] != 'running':break
            if task['state'] == 'queued':run_task(task, resume)
        stopped = store.get_run(run_id)['state'] != 'running'
        store.finish_run(run_id, 'stopped' if stopped else 'finished')
    except Exception:
        store.finish_run(run_id, 'failed')
