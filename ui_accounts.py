"""Account UI: sign in directly in the browser, without storing passwords."""
import subprocess
import sys
import uuid

import streamlit as st

from browser_sessions import state_path, session_key
from db import ROOT, DATA, get_jobs
from discovery import DEFAULT_SOURCES, clean_url


def render_accounts():
    st.subheader('Accounts & Sessions')
    st.write('Open the employer portal, create an account or sign in yourself, and complete any MFA. The browser saves session cookies locally for later application windows. Accounts can be specific to an employer and portal; a saved session may expire or require another login.')
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
    st.caption('Use the same portal hostname as the application when possible. Passwords are entered only in the employer browser. Saved cookies are credentials: keep data/account-sessions private. Discovery continues to use public pages, not account sessions.')
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
        if url and state_path(clean_url(url)).exists():
            st.success('A reusable session exists for this portal. This does not guarantee the employer still considers it signed in.')
            if st.button('Forget saved session', disabled=active):
                # Acquire the same OS lock used by browser workers before deletion.
                from browser_sessions import session_lock
                with session_lock(url):
                    state_path(url).unlink(missing_ok=True)
                st.success('Saved login session removed. This does not revoke the employer-side session.')
    except Exception as exc:
        if url:st.caption(str(exc))
