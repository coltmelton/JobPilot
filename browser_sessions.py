"""Manual account sign-in and reusable, employer-scoped browser sessions."""
import argparse
import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from db import DATA


def session_key(url):
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('Use an https:// portal URL without credentials.')
    host = parts.hostname.lower()
    # Workday accounts belong to the employer tenant, not all Workday sites.
    if host.endswith('.myworkdayjobs.com'):
        scope = host.split('.')[0] + '.myworkdayjobs.com'
    elif host in ('jobs.lever.co', 'jobs.eu.lever.co', 'boards.greenhouse.io', 'job-boards.greenhouse.io'):
        tenant = next(iter(filter(None, parts.path.split('/'))), '')
        scope = host.replace('job-boards.', 'boards.') + '/' + tenant
    else:
        scope = host
    return hashlib.sha256(scope.encode()).hexdigest()[:24]


def state_path(url):
    return DATA / 'account-sessions' / (session_key(url) + '.json')


@contextmanager
def session_lock(url, wait=False):
    """Serialise users of the same account session, including batch workers."""
    folder = DATA / 'account-sessions'
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / (session_key(url) + '.lock')
    handle = lock.open('a+b')
    handle.seek(0, 2)
    if handle.tell() == 0:
        handle.write(b'0');handle.flush()
    started = time.monotonic()
    try:
        while True:
            try:
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if not wait or time.monotonic() - started > 7200:
                    raise RuntimeError('This portal already has an open JobPilot browser. Close it before opening another for the same account.') from None
                time.sleep(0.5)
        yield
    finally:
        handle.close()  # The OS releases the lock even after a process crash.


def save_state(context, url):
    path = state_path(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    context.storage_state(path=str(temporary), indexed_db=True)
    temporary.replace(path)


def open_account(url, forget=False):
    from playwright.sync_api import sync_playwright
    with session_lock(url):
        saved = state_path(url)
        if forget:
            saved.unlink(missing_ok=True)
            print('Saved session removed.', flush=True)
            return
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)
            context = browser.new_context(storage_state=str(saved) if saved.exists() else None)
            page = context.new_page()
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=60000)
                print('Sign in or create your account yourself. Complete MFA if required. Leave this window open until finished; session state is saved periodically.', flush=True)
                while browser.is_connected() and any(not item.is_closed() for item in context.pages):
                    try:
                        save_state(context, url)
                        # Pump browser events so closing a window is detected.
                        context.pages[0].wait_for_timeout(2000)
                    except Exception:
                        if not browser.is_connected() or not context.pages:
                            break
                        time.sleep(1)
            finally:
                try:
                    save_state(context, url)
                except Exception:
                    pass
                browser.close()


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--forget', action='store_true')
    args = parser.parse_args()
    open_account(args.url, args.forget)
