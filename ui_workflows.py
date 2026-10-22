"""Background batch dashboard and in-app employer form assistance."""
import json
import subprocess
import sys
import time

import pandas as pd
import streamlit as st

import db
import workflow_store as store
from batch_control import force_stop_batches
from form_intelligence import choose_resume
from credential_vault import credential_status, save_credentials, allow_shared, forget_credentials


def render_credentials(url=None, key='accounts'):
    st.subheader('Encrypted application credentials')
    st.caption('Stored outside the project in your Windows-user encrypted vault. Passwords are never written to profile.json or application logs. Shared credentials are only used on portals you explicitly allow.')
    with st.form(f'{key}_shared_login', clear_on_submit=True):
        email = st.text_input('Shared application email', key=f'{key}_shared_email')
        password = st.text_input('Shared application password', type='password', key=f'{key}_shared_password')
        if st.form_submit_button('Save shared application login'):
            try:save_credentials(email,password);st.success('Shared login encrypted and saved.')
            except Exception as exc:st.error(str(exc))
    if credential_status():
        st.caption('A shared application login is saved.')
        if st.button('Delete shared application login',key=f'{key}_delete_shared'):
            forget_credentials();st.success('Shared login deleted; portal-specific logins are separate.')
    if url:
        st.write('Current portal: '+url)
        if st.button('Allow shared login on this portal', key=f'{key}_approve_shared', disabled=not credential_status()):
            try:allow_shared(url);st.success('Shared login allowed on this portal. Retry login in the inbox.')
            except Exception as exc:st.error(str(exc))
        with st.form(f'{key}_portal_login',clear_on_submit=True):
            email=st.text_input('Email for this portal',key=f'{key}_portal_email')
            password=st.text_input('Password for this portal',type='password',key=f'{key}_portal_password')
            if st.form_submit_button('Save login for this portal'):
                try:save_credentials(email,password,url);st.success('Portal login encrypted and saved.')
                except Exception as exc:st.error(str(exc))
        if credential_status(url):
            st.caption('Credentials are configured for this portal. Employer acceptance is checked when signing in.')
            if st.button('Forget login for this portal',key=f'{key}_forget_portal'):
                forget_credentials(url);st.success('Portal credentials and shared-login permission removed.')


def render_batch(jobs):
    st.subheader('Background application queue')
    st.caption('Force stop immediately closes this project’s batch workers and their browser windows, including older batches. Unsaved employer form entries may be lost; submitted applications remain submitted.')
    if st.button('Force stop all batches', key='force_stop_batches', type='primary'):
        try:
            force_stop_batches()
            st.success('All JobPilot batches stopped. You can start a new batch.')
        except Exception as exc:
            st.error(f'Could not fully stop the batch: {exc}')
    remembered=db.profile().get('form_answers',{})
    if remembered:
        with st.expander(f'Remembered routine answers ({len(remembered)})'):
            st.dataframe(pd.DataFrame([{'Question':question,'Answer':answer} for question,answer in remembered.items()]),hide_index=True)
            if st.button('Forget remembered routine answers'):
                applicant=db.profile();applicant.pop('form_answers',None);db.save_profile(applicant);st.rerun()
    st.write('Applications run one at a time without opening Chrome windows. The batch fills supported fields and advances supported steps, then pauses here for login, account creation, verification, missing answers or final review.')
    st.caption('Introductory Apply buttons are automatic. Resume autofill is preferred whenever offered; choose your resume below. Supported dropdowns use your saved profile and remembered answers.')
    if jobs:
        candidates=[job for job in jobs if job['status']!='Applied']
        options={f"#{job['id']} — {job['company']} — {job['title']}":job['id'] for job in candidates}
        all_jobs=st.checkbox('Select all jobs not marked Applied')
        selected=st.multiselect('Choose jobs to prepare',list(options),default=list(options) if all_jobs else [])
        folder=db.DATA/'documents'
        files=sorted(path.name for path in folder.glob('*') if path.is_file()) if folder.exists() else []
        automatic='Auto-select saved resume'
        resume_options=[automatic]+files
        preferred=choose_resume('',db.profile(),folder) or automatic
        resume=st.selectbox('Resume for batch',resume_options,index=resume_options.index(preferred) if preferred in resume_options else 0)
        use_shared=st.checkbox('Allow my shared saved login on the selected employer portals',disabled=not credential_status())
        if st.button('Launch selected applications',type='primary',disabled=not selected):
            run_id=None
            try:
                ids=[options[label] for label in selected]
                if use_shared:
                    for job in candidates:
                        if job['id'] in ids:allow_shared(job['url'])
                run_id=store.create_run(ids,'' if resume==automatic else resume)
                folder=db.DATA/'logs';folder.mkdir(parents=True,exist_ok=True)
                with (folder/f'batch-{run_id}.log').open('w',encoding='utf-8') as log:
                    process=subprocess.Popen([sys.executable,str(db.ROOT/'batch.py'),'--run-id',run_id],cwd=db.ROOT,stdout=log,stderr=subprocess.STDOUT)
                st.session_state['workflow_process']=process
                st.success('Background batch started. Requests for help appear in the inbox below.')
            except Exception as exc:
                if run_id:store.finish_run(run_id,'failed')
                st.error(str(exc))
    else:st.info('Import jobs first. Previous batches remain visible below.')
    render_inbox()


def _send(task,view,action,**payload):
    try:
        store.send_command(task['id'],action,view.get('view_id'),**payload)
        st.success('Request sent. The worker will refresh this view after processing it.')
    except Exception as exc:st.error(str(exc))


@st.fragment(run_every='5s')
def render_batch_notice():
    active=next((run for run in store.runs() if run['state'] in ('running','stopping')),None)
    if not active:return
    pending=[task for task in store.tasks(active['id']) if task['state'] in store.NEEDS_HELP]
    if pending:
        st.warning(f"Batch needs your help on {len(pending)} application(s). Open Batch Launch to respond.")
        event=(pending[0]['id'],pending[0]['state'])
        if st.session_state.get('batch_notice')!=event:
            st.toast(f"{pending[0]['company']}: {pending[0]['message']}",icon='⚠️')
            st.session_state['batch_notice']=event
    else:st.caption('An application batch is running in the background.')


@st.fragment(run_every='3s')
def render_inbox():
    runs=store.runs()
    if not runs:return
    st.subheader('Batch progress and assistance inbox')
    selected=st.selectbox('Batch to inspect',[run['id'] for run in runs],format_func=lambda rid: f"{rid[:8]} — {next(run['state'] for run in runs if run['id']==rid)}")
    run=next(run for run in runs if run['id']==selected)
    tasks=store.tasks(selected)
    pending=[task for task in tasks if task['state'] in store.NEEDS_HELP]
    complete=sum(task['state'] in store.TERMINAL for task in tasks)
    st.progress(complete/max(1,len(tasks)),text=f'{complete}/{len(tasks)} tasks finished; {len(pending)} need your help')
    st.dataframe(pd.DataFrame(tasks)[['company','title','state','message','url']] if tasks else pd.DataFrame(),hide_index=True,column_config={'url':st.column_config.LinkColumn('Job',display_text='Open job ↗')},use_container_width=True)
    if run['state'] in ('running','stopping'):
        if time.time()-run['heartbeat']>60:st.warning('The batch has not sent a heartbeat recently. It may be stuck or the worker may have stopped.')
        if time.time()-run['heartbeat']>120 and st.button('End inactive batch',key=f'end_{selected}'):
            store.finish_run(selected,'stopped');st.info('Inactive batch closed. You can launch a new batch.')
        if st.button('Stop this batch',key=f'stop_{selected}'):
            store.set_run_state(selected,'stopping');st.info('Stop requested. The current browser will close and queued tasks will stop.')
    if not pending:
        if run['state']=='running':st.info('The worker is preparing the next supported step. This inbox updates automatically.')
        return
    st.warning(f'{len(pending)} application(s) need your attention. The queue waits for you.')
    chosen=st.selectbox('Application needing help',[task['id'] for task in pending],format_func=lambda tid: next(f"{task['company']} — {task['title']}" for task in pending if task['id']==tid))
    task=next(task for task in pending if task['id']==chosen)
    view=json.loads(task['snapshot'] or '{}')
    st.write(task['message'])
    if not view:return
    if task['state']=='needs_information':
        if st.button('Leave remaining optional fields blank and continue',key=f"optional_{task['id']}"):_send(task,view,'continue_optional')
        if view.get('resume_upload',{}).get('status')=='attempted':
            st.caption('A resume upload was attempted, but acceptance could not be confirmed. Automatic repeat uploads are blocked.')
        if view.get('resume_upload',{}).get('status'):
            if st.button('Retry resume upload if the previous upload failed',key=f"retry_upload_{task['id']}"):_send(task,view,'retry_upload')
    st.caption('Employer page: '+view['url'])
    try:
        image=store.screenshot_bytes(task['id'])
        if image:
            with st.expander('Employer page preview',expanded=True):st.image(image,use_container_width=True)
    except Exception:st.error('The saved preview could not be decrypted for this Windows user.')
    if task['state'] in ('needs_credentials','login_failed','account_required'):
        with st.expander('Saved login and account setup',expanded=True):render_credentials(view['url'],key=f"inbox_{task['id']}")
        if st.button('Retry with saved credentials',key=f"retry_{task['id']}"):_send(task,view,'retry_login')
        if task['state']=='account_required':st.info('Choose the employer’s Create account/Register action below if needed. Enter registration fields here and explicitly send the employer’s registration action. Email verification may require another step.')
    _render_fields(task,view)
    actions=view.get('actions',[])
    if actions:
        chosen_action=st.selectbox('Employer page action',['']+[action['id'] for action in actions],format_func=lambda aid:'Choose an action' if not aid else next(action['label'] for action in actions if action['id']==aid),key=f"action_{view['view_id']}")
        action_label=next((action['label'] for action in actions if action['id']==chosen_action),'')
        if st.button('Send employer action: '+(action_label or '(choose above)'),disabled=not chosen_action,key=f"act_{view['view_id']}"):_send(task,view,'act',action_id=chosen_action)
    st.caption('Employer actions are real clicks on the live website. A Submit/Apply/Finish action may send your application; inspect the preview and answers first.')
    left,right=st.columns(2)
    if left.button('Resume automation',key=f"resume_{task['id']}"):_send(task,view,'resume')
    if right.button('Refresh employer view',key=f"refresh_{task['id']}"):_send(task,view,'refresh')
    if st.button('Skip this job and continue batch',key=f"skip_{task['id']}"):_send(task,view,'skip')
    if task['state'] in store.NEEDS_HELP:
        st.caption('Some CAPTCHA, passkey and device checks cannot be completed through mirrored controls. A manual browser is an optional exception; unsaved page entries may need re-entering after the handoff.')
        if st.button('Open manual browser for this job',key=f"manual_{task['id']}"):_send(task,view,'open_browser')


def _render_fields(task,view):
    fields=[field for field in view.get('fields',[]) if not field['disabled'] and (not field['readonly'] or field['type']=='combobox')]
    if not fields:return
    st.caption('Enter only fields you want to change. Blank text and “Leave unchanged” preserve employer values. Credentials and one-time codes sent here are encrypted through the local queue.')
    changes={}
    with st.form(f"fields_{view['view_id']}",clear_on_submit=True):
        for field in fields:
            label=field['label']+(' (required)' if field['required'] else '')+(' — already populated' if field['populated'] else '')
            if field.get('frame'):label+=' ['+field.get('origin','embedded frame')+']'
            key=f"field_{view['view_id']}_{field['id']}"
            kind=field['type']
            if kind in ('checkbox','radio'):
                value=st.selectbox(label,['Leave unchanged','Yes / checked','No / unchecked'],key=key)
                if value!='Leave unchanged':changes[field['id']]=value=='Yes / checked'
            elif kind=='select':
                options={f"{option['index']}: {option['label']}":option['index'] for option in field['options'] if not option['disabled']}
                value=st.selectbox(label,['Leave unchanged']+list(options),key=key)
                if value!='Leave unchanged':changes[field['id']]=options[value]
            elif kind=='combobox':
                if st.checkbox('Open choices: '+label,key=key):changes[field['id']]=True
            elif kind=='file':
                folder=db.DATA/'documents'
                files=sorted(path.name for path in folder.glob('*') if path.is_file()) if folder.exists() else []
                value=st.selectbox(label,['Leave unchanged']+files,key=key)
                if value!='Leave unchanged':changes[field['id']]=value
            else:
                value=st.text_area(label,key=key) if kind=='textarea' else st.text_input(label,type='password' if kind=='password' else 'default',key=key)
                if value:changes[field['id']]=value
        remember=st.checkbox('Remember these routine answers for other applications',key=f"remember_{view['view_id']}",help='Reuses exact matching questions. Passwords, verification codes, certifications and sensitive questions are excluded.')
        if st.form_submit_button('Send entries to employer page'):_send(task,view,'fields',changes=changes,remember=remember)
