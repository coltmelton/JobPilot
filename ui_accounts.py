"""Account UI: sign in directly in the browser, without storing passwords."""
import subprocess
import sys
import uuid

import streamlit as st

from browser_sessions import state_path, session_key
from db import ROOT, DATA, get_jobs
from discovery import DEFAULT_SOURCES, clean_url
from ui_workflows import render_credentials
from credential_vault import browser_state_exists,forget_browser_state


def render_accounts():
    st.subheader('Accounts & Sessions')
    st.write('Save your application login below. Batch Launch uses it in the background and asks for help inside the dashboard when an account, verification or extra information is needed. You can still open a manual browser here as an optional fallback.')
    portals = {'Custom portal URL': ''}
    seen = set()
    for job in get_jobs():
        key = session_key(job['url'])
        if key not in seen:
            portals[f"{job['company']} — {job['url'].split('/')[2]}"] = job['url']
            seen.add(key)
    if len(portals) == 1:
        portals.update({url: url for url in DEFAULT_SOURCES})
    selected = st.selectbox('Employer portal', list(portals))
    url = st.text_input('Login / careers URL', value=portals[selected])
    valid_url=None
    try:
        if url:valid_url=clean_url(url)
    except ValueError:st.caption('Enter a complete https:// portal URL to configure its login.')
    render_credentials(valid_url)
    st.caption('Background batches save encrypted sessions in the private vault. The optional legacy manual-browser helper below still uses data/account-sessions. Discovery uses public pages, not your credentials.')
    task = st.session_state.get('account_task')
    active = task is not None and task['process'].poll() is None
    if st.button('Open portal to sign in / create account', disabled=active):
        try:
            url = clean_url(url)
            folder = DATA/'logs';folder.mkdir(parents=True, exist_ok=True)
            log_path = folder/f'account-{uuid.uuid4().hex}.log'
            with log_path.open('w', encoding='utf-8') as log:
                process = subprocess.Popen([sys.executable, str(ROOT/'browser_sessions.py'), '--url', url], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            st.session_state['account_task'] = {'process': process, 'log': log_path}
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if task:
        st.info('Account browser is open. Close it when finished before launching an application for the same portal.' if active else 'Account browser closed. Check the log if sign-in did not open.')
        if st.button('Refresh account status'):
            st.rerun()
        if task['log'].exists():
            with st.expander('Account browser log'):
                st.code(task['log'].read_text(encoding='utf-8', errors='replace')[-6000:])
    try:
        if url and (state_path(clean_url(url)).exists() or browser_state_exists(clean_url(url))):
            st.success('A reusable session exists for this portal. This does not guarantee the employer still considers it signed in.')
            if st.button('Forget saved session', disabled=active):
                # Acquire the same OS lock used by browser workers before deletion.
                from browser_sessions import session_lock
                with session_lock(url):
                    state_path(url).unlink(missing_ok=True)
                    forget_browser_state(url)
                st.success('Saved login session removed. This does not revoke the employer-side session.')
    except Exception as exc:
        if url:st.caption(str(exc))
