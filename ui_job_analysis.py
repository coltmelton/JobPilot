"""Nonblocking description retrieval controls shared by queue and review pages."""
import subprocess
import sys
import uuid

import streamlit as st

from db import ROOT, DATA


def description_controls(job_id=None):
    task = st.session_state.get('queue_analysis_task')
    active = task is not None and task['process'].poll() is None
    if st.button('Fetch full job description' if job_id else 'Fetch missing descriptions for queued jobs', disabled=active):
        folder = DATA/'logs';folder.mkdir(parents=True, exist_ok=True)
        logfile = folder/f'descriptions-{uuid.uuid4().hex}.log'
        args = [sys.executable, str(ROOT/'analyze_queue.py'), '--limit', '20']
        if job_id:
            args += ['--job-id', str(job_id)]
        with logfile.open('w', encoding='utf-8') as log:
            process = subprocess.Popen(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        st.session_state['queue_analysis_task'] = {'process': process, 'log': logfile}
        st.rerun()
    if task:
        st.caption('Fetching public descriptions in the background (up to 20 missing descriptions per run).' if active else 'Description retrieval finished. Rankings update on refresh.')
        if st.button('Refresh description status'):
            st.rerun()
        if task['process'].poll() not in (None, 0):
            st.error('Description retrieval failed. Check the log; rerun setup.cmd if a browser dependency is missing.')
        if task['log'].exists():
            with st.expander('Description retrieval log'):
                st.code(task['log'].read_text(encoding='utf-8', errors='replace')[-6000:])
