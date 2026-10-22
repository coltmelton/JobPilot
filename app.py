import json, subprocess, sys
import uuid
import time
from pathlib import Path
import pandas as pd
import streamlit as st
from db import ROOT,DATA,get_jobs,get_job,save_job,update_job,profile,save_profile,clear_job_queue,queue_revision
from applicant import TEXT_SECTIONS, CHOICES, HISTORY, CHECKLIST, history_rows
from discovery import DEFAULT_SOURCES, parse_sources, clean_url
from matching import assess_job, resume_fingerprint
from ui_matching import render_resume, rank_and_filter, explain_candidates
from ui_accounts import render_accounts
from ui_job_analysis import description_controls

st.set_page_config(page_title='JobPilot',page_icon='🧭',layout='wide')
st.title('🧭 JobPilot')
st.caption('Local-first job application control center · You control final submission')
revision=queue_revision()
if st.session_state.get('queue_revision')!=revision:
    for key in list(st.session_state):
        if key.startswith(('discovery_review_','discovery_table_','discovery_revision_')) or key in ('discovery_results','discovery_loaded','discovery_task'):
            del st.session_state[key]
    st.session_state['queue_revision']=revision
page=st.sidebar.radio('Navigate',['Dashboard','Discover Jobs','Job Queue','Bulk Import','Resume & Matching','My Profile','Documents','Accounts & Sessions','Review & Launch','Batch Launch'])
COMPANIES=['RTX / Raytheon','Anduril','Palantir','Lockheed Martin','Parker Hannifin','Parker Aerospace','KLA','Sartorius','Pfizer','Northrop Grumman']
JOBS=get_jobs()
if page=='Dashboard':
    cols=st.columns(4)
    for col,(label,count) in zip(cols,[('Total',len(JOBS)),('Saved',sum(j['status']=='Saved' for j in JOBS)),('In progress',sum(j['status']=='In progress' for j in JOBS)),('Applied',sum(j['status']=='Applied' for j in JOBS))]):col.metric(label,count)
    st.subheader('Target employers')
    st.write(' • '.join(COMPANIES))
    st.info('Start in Discover Jobs to scan careers pages, or add individual application URLs in Job Queue. Review discovered postings before importing them.')
elif page=='Discover Jobs':
    st.subheader('Discover jobs from careers pages')
    st.caption('Paste career-page or individual posting URLs, separated by newlines or |. Scans public pages without sending your profile or submitting forms. Resume prioritisation runs locally. Results are candidates for your review; some portals may need manual browsing.')
    sources_text=st.text_area('Career page links',value='\n'.join(DEFAULT_SOURCES),height=240)
    col1,col2=st.columns(2)
    pages=col1.number_input('Maximum pages per source',min_value=1,max_value=20,value=3)
    limit=col2.number_input('Maximum results per source',min_value=1,max_value=1000,value=100)
    details_limit=st.number_input('Additional full descriptions to fetch for matching',min_value=0,max_value=200,value=20)
    headed=st.checkbox('Show browser for manual consent / verification (waits 30 seconds per rendered source)')
    task=st.session_state.get('discovery_task')
    active=task is not None and task['process'].poll() is None
    if st.button('Scan career pages',type='primary',disabled=active):
        try:
            sources=parse_sources(sources_text)
            if not sources:raise ValueError('Paste at least one https:// careers URL.')
            folder=DATA/'discovery'/uuid.uuid4().hex
            folder.mkdir(parents=True)
            (folder/'sources.txt').write_text('\n'.join(sources),encoding='utf-8')
            with (folder/'scan.log').open('w',encoding='utf-8') as log:
                command=[sys.executable,str(ROOT/'discovery.py'),'--sources-file',str(folder/'sources.txt'),'--output',str(folder/'results.json'),'--pages',str(pages),'--limit',str(limit),'--details',str(details_limit)]
                if headed:command.append('--headed')
                process=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            st.session_state['discovery_task']={'process':process,'folder':folder}
            st.rerun()
        except Exception as exc:st.error(f'Unable to start scan: {exc}')
    if task:
        if active:
            st.info('Scanning in the background. You can use other pages while it runs. Refresh scan status to see progress.')
            if st.button('Refresh scan status'):st.rerun()
            if st.button('Stop scan'):
                task['process'].terminate();task['process'].wait(timeout=10);st.rerun()
        elif task['process'].returncode==0:
            output=task['folder']/'results.json'
            if st.session_state.get('discovery_loaded')!=str(output):
                st.session_state['discovery_results']=json.loads(output.read_text(encoding='utf-8'))
                st.session_state['discovery_loaded']=str(output)
        else:st.error('Scan failed. Check the log below. If Chromium is missing, rerun setup.cmd.')
        logfile=task['folder']/'scan.log'
        if logfile.exists():
            with st.expander('Scan progress / log'):st.code(logfile.read_text(encoding='utf-8',errors='replace')[-12000:])
    result=st.session_state.get('discovery_results')
    if not result and not active:
        completed=sorted((DATA/'discovery').glob('*/results.json'),key=lambda path:path.stat().st_mtime,reverse=True) if (DATA/'discovery').exists() else []
        if completed and st.button('Load latest saved discovery results'):
            try:
                st.session_state['discovery_results']=json.loads(completed[0].read_text(encoding='utf-8'))
                st.session_state['discovery_loaded']=str(completed[0]);st.rerun()
            except (ValueError,OSError) as exc:st.error(f'Could not load previous results: {exc}')
    if result:
        st.subheader('Source reports')
        st.dataframe(pd.DataFrame(result['reports']),hide_index=True,column_config={'source':st.column_config.LinkColumn('Source')},use_container_width=True)
        candidates=result['jobs']
        described=sum(bool(j.get('description')) for j in candidates)
        st.caption(f'{described} of {len(candidates)} candidates have descriptions. Others have unverified requirements; fetch more or inspect them manually.')
        if st.button('Fetch more missing descriptions',disabled=active or not candidates or details_limit==0):
            folder=DATA/'discovery'/uuid.uuid4().hex;folder.mkdir(parents=True)
            (folder/'input.json').write_text(json.dumps(result),encoding='utf-8')
            with (folder/'scan.log').open('w',encoding='utf-8') as log:
                process=subprocess.Popen([sys.executable,str(ROOT/'discovery.py'),'--enrich-file',str(folder/'input.json'),'--output',str(folder/'results.json'),'--details',str(details_limit)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            st.session_state['discovery_task']={'process':process,'folder':folder};st.rerun()
        st.caption(f'{len(candidates)} unique candidate postings from the last completed scan. No applications have been added yet.')
        candidates=rank_and_filter(candidates)
        include=st.text_input('Title keywords (comma-separated; match any)',placeholder='software, engineer, intern')
        exclude=st.text_input('Exclude title keywords (comma-separated)',placeholder='principal, director')
        location_filter=st.text_input('Location contains (blank locations will not match)')
        companies=st.multiselect('Companies',sorted({j['company'] for j in candidates}))
        terms=lambda text:[term.strip().casefold() for term in text.split(',') if term.strip()]
        filtered=[j for j in candidates if (not terms(include) or any(t in j['title'].casefold() for t in terms(include))) and not any(t in j['title'].casefold() for t in terms(exclude)) and location_filter.strip().casefold() in j.get('location','').casefold() and (not companies or j['company'] in companies)]
        explain_candidates(filtered)
        if filtered:
            existing={j['url'] for j in get_jobs()}
            frame=pd.DataFrame([dict(Select=False,**j,Already_saved=j['url'] in existing) for j in filtered])
            st.caption('Check Select for postings to import. Page-link titles can include extra text; edit titles and locations before importing. Open each URL to verify the role.')
            view_signature=resume_fingerprint(json.dumps([(j['url'],j.get('match_score'),j.get('match_reasons')) for j in filtered]))
            editor_key=f"discovery_review_{st.session_state.get('discovery_loaded','')}_{include}_{exclude}_{location_filter}_{companies}_{view_signature}"
            table_key=f'discovery_table_{editor_key}'
            revision_key=f'discovery_revision_{editor_key}'
            frame=st.session_state.get(table_key,frame).copy()
            revision=st.session_state.get(revision_key,0)
            widget_key=f'{editor_key}_v{revision}'
            select_col,clear_col=st.columns(2)
            select_all=select_col.button('Select all visible results')
            clear_all=clear_col.button('Clear selection')
            if select_all or clear_all:
                editor_state=st.session_state.get(widget_key,{})
                for index,values in editor_state.get('edited_rows',{}).items():
                    for column,value in values.items():
                        frame.at[int(index),column]=value
                frame['Select']=select_all
                st.session_state[table_key]=frame.copy()
                revision+=1
                st.session_state[revision_key]=revision
                widget_key=f'{editor_key}_v{revision}'
            editable=['Select','company','title','location']
            visible=['Select','company','title','location','match_score','match','clearance','experience_fit','matched_skills','description_status','url','Already_saved']
            reviewed=st.data_editor(frame,hide_index=True,disabled=[column for column in frame.columns if column not in editable],column_order=[column for column in visible if column in frame.columns],column_config={'url':st.column_config.LinkColumn('Job / application',display_text='Open job ↗',help='Open the employer posting or application page to inspect it.')},key=widget_key,use_container_width=True)
            st.caption(f"{int(reviewed['Select'].sum())} of {len(reviewed)} visible postings selected.")
            if st.button('Import selected postings'):
                selected=reviewed[reviewed['Select']].to_dict('records')
                count=0;errors=[]
                for item in selected:
                    try:
                        url=clean_url(str(item['url']))
                        title=str(item['title']).strip();company=str(item['company']).strip()
                        if not title or not company:raise ValueError('Company and title are required')
                        if url in existing:continue
                        job_id=save_job(company,title,url,str(item.get('location') or ''))
                        update_job(job_id,application_details=json.dumps({key:item[key] for key in ('description','description_status','source','description_fetched_at') if isinstance(item.get(key),str)}))
                        existing.add(url);count+=1
                    except Exception as exc:errors.append(str(exc))
                st.success(f'Added {count} new postings; existing URLs skipped.')
                if errors:st.error('; '.join(errors))
        elif candidates:st.info('No postings match these filters. Clear a filter to see more results.')
elif page=='Job Queue':
    if st.session_state.get('queue_reset_message'):
        st.success(st.session_state.pop('queue_reset_message'))
    with st.expander('Start over — clear imported jobs'):
        st.write('Clear all queued jobs, including their statuses, notes and per-job answers. A backup is saved first. Your resume, profile, matching settings and saved logins are kept. Close application browser windows before resetting.')
        if st.button('Back up and clear job queue',disabled=not JOBS):
            try:
                count,backup=clear_job_queue()
                for key in list(st.session_state):
                    if key.startswith(('discovery_review_','discovery_table_','discovery_revision_')) or key in ('discovery_results','discovery_loaded','discovery_task'):
                        del st.session_state[key]
                st.session_state['queue_reset_message']=f'Cleared {count} jobs. Backup: {backup.name if backup else "not needed"}. Go to Discover Jobs to scan, filter and import a new list.'
                st.rerun()
            except Exception as exc:st.error(f'Could not reset the queue: {exc}')
    with st.form('add'):
        st.subheader('Add a position')
        a,b=st.columns(2)
        company=a.selectbox('Company',COMPANIES+['Other'])
        title=b.text_input('Job title')
        url=st.text_input('Application URL (https://...)')
        location=st.text_input('Location (optional)')
        if st.form_submit_button('Save position'):
            if title.strip() and url.startswith('https://'):
                save_job(company,title.strip(),url.strip(),location.strip());st.success('Saved');st.rerun()
            else:st.error('Provide a title and https:// URL.')
    st.subheader('Positions')
    if JOBS:
        description_controls()
        queue=[]
        for job in JOBS:
            detail=json.loads(job.get('application_details') or '{}')
            description=detail.get('posting_description') or detail.get('description','')
            queue.append(dict(job,description=description,description_status='Manually supplied' if detail.get('posting_description') else detail.get('description_status','Not fetched')))
        ranked=rank_and_filter(queue,prefix='queue')
        columns=['id','company','title','location','status','match_score','match','clearance','experience_fit','url']
        st.dataframe(pd.DataFrame(ranked,columns=[column for column in columns if column in (ranked[0] if ranked else JOBS[0])]),hide_index=True,column_config={'url':st.column_config.LinkColumn('Job / application',display_text='Open job ↗',help='Open the employer posting or application page to inspect it.')},use_container_width=True)
        explain_candidates(ranked)
    else:st.info('No saved positions yet.')
elif page=='Bulk Import':
    st.subheader('Import multiple application links')
    st.info('For career-page links or a list containing only URLs separated by |, use Discover Jobs in the sidebar first.')
    st.caption('One application per line. Use: Company | Job title | https://application-url | Optional location')
    bulk=st.text_area('Application links',height=220,placeholder='Anduril | Software Engineer | https://example.com/apply/123 | California')
    if st.button('Import jobs'):
        added=0;errors=[]
        for n,line in enumerate(bulk.splitlines(),1):
            if not line.strip():continue
            parts=[x.strip() for x in line.split('|')]
            if len(parts)<3 or not parts[2].startswith('https://'):
                errors.append(n);continue
            save_job(parts[0],parts[1],parts[2],parts[3] if len(parts)>3 else '')
            added+=1
        st.success(f'Processed {added} valid rows; duplicate URLs are ignored.')
        if errors:st.error(f'Invalid rows: {errors}')
elif page=='Batch Launch':
    st.subheader('Concurrent application preparation')
    st.caption('Prepares applications in visible browser windows. Jobs on the same portal run one at a time to share your login safely; different portals can run concurrently. It does not submit or automatically advance through multi-step forms.')
    if not JOBS:st.info('Import or add jobs first.')
    else:
        selections={f"#{j['id']} — {j['company']} — {j['title']}":j['id'] for j in JOBS}
        selected=st.multiselect('Choose jobs to prepare',list(selections))
        workers=st.slider('Concurrent browser sessions',min_value=1,max_value=5,value=3)
        docs=list((DATA/'documents').glob('*')) if (DATA/'documents').exists() else []
        chosen=st.selectbox('Resume for batch', ['None']+[f.name for f in docs])
        st.warning('Launch only as many browser windows as your machine can handle. Verification, login, written questions, and final review may need your input in each window.')
        if st.button('Launch selected applications',type='primary',disabled=not selected):
            cmd=[sys.executable,str(ROOT/'batch.py'),'--job-ids',','.join(str(selections[s]) for s in selected),'--workers',str(workers)]
            if chosen!='None':cmd+=['--resume',chosen]
            try:
                with (DATA/'batch.log').open('a',encoding='utf-8') as logfile:
                    subprocess.Popen(cmd,cwd=ROOT,stdout=logfile,stderr=subprocess.STDOUT,start_new_session=True)
                st.success(f'Started batch of {len(selected)} applications. Per-job logs: data/logs/')
            except Exception as e:st.error(f'Unable to launch batch: {e}')
elif page=='Resume & Matching':
    render_resume()
elif page=='Accounts & Sessions':
    render_accounts()
elif page=='My Profile':
    p=profile()
    with st.form('profile'):
        st.subheader('Reusable applicant details')
        st.caption('Saved locally in data/profile.json. Fill only what you need. Leave SSNs, birth dates, identity documents, passwords, and classified details out of this app.')
        v=dict(p)
        for section, fields in TEXT_SECTIONS.items():
            st.subheader(section)
            columns=st.columns(2)
            for i,(key,label) in enumerate(fields.items()):
                v[key]=columns[i%2].text_input(label,value=p.get(key,''))
        st.subheader('Defense screening reference — manual entry in employer portals')
        st.caption('Optional, self-reported reference only; these fields are never used by profile autofill. Work authorization, citizenship, export-control status, and clearance eligibility are separate questions. Use each posting’s exact wording; the employer determines eligibility.')
        for key,(label,options) in CHOICES.items():
            choices=['Not provided']+options
            saved=p.get(key,'Not provided')
            if saved not in choices:choices.append(saved)
            v[key]=st.selectbox(label,choices,index=choices.index(saved))
        v['screening_notes']=st.text_area('Screening notes / questions for recruiter (unclassified only)',value=p.get('screening_notes',''))
        for key,(label,columns) in HISTORY.items():
            st.subheader(label)
            st.caption('Add or delete rows as needed. Dates can use month/year. Leave optional fields blank.')
            frame=pd.DataFrame(p.get(key,[]),columns=columns).fillna('').astype(str)
            edited=st.data_editor(frame,num_rows='dynamic',hide_index=True,key=f'profile_{key}',use_container_width=True)
            v[key]=history_rows(edited.to_dict('records'),columns)
        st.subheader('Reusable written responses')
        for key,label in {'professional_summary':'Professional summary', 'defense_motivation':'Why defense / aerospace?', 'technical_example':'Technical accomplishment (situation, action, result)', 'teamwork_example':'Teamwork / leadership example'}.items():
            v[key]=st.text_area(label,value=p.get(key,''))
        if st.form_submit_button('Save profile'):save_profile(v);st.success('Profile saved')
elif page=='Documents':
    st.subheader('Application documents')
    folder=DATA/'documents';folder.mkdir(exist_ok=True)
    uploaded=st.file_uploader('Add resumes, cover letters or other application files',type=['pdf','docx','txt'],accept_multiple_files=True)
    if st.button('Save uploaded documents'):
        for f in uploaded or []:
            safe=Path(f.name).name
            if safe.lower().endswith(('.pdf','.docx','.txt')):(folder/safe).write_bytes(f.getvalue())
        st.success('Documents saved locally')
    files=sorted(folder.iterdir())
    if files:st.write('\n'.join(f'- {x.name}' for x in files))
    else:st.info('No files uploaded.')
else:
    st.subheader('Review and launch')
    if not JOBS:st.info('Add a position in Job Queue first.')
    else:
        options={f"#{j['id']} — {j['company']} — {j['title']}":j['id'] for j in JOBS}
        jid=options[st.selectbox('Choose application',list(options))];j=get_job(jid)
        st.link_button('View application page',j['url'])
        description_controls(jid)
        details=json.loads(j['application_details'] or '{}')
        with st.expander('Application requirements and preparation',expanded=True):
            with st.form('application_details'):
                updated=dict(details)
                for key,label in {'requisition_id':'Requisition / job ID', 'deadline':'Application deadline (include timezone if given)', 'recruiter':'Recruiter / referral contact', 'required_clearance':'Clearance requirement (copy posting wording)', 'citizenship_export':'Citizenship / export-control requirement (copy posting wording)', 'required_documents':'Required documents / resume version', 'posting_notes':'Qualifications, location, travel, shifts and other requirements'}.items():
                    updated[key]=st.text_area(label,value=details.get(key,'')) if key in ('posting_notes','citizenship_export') else st.text_input(label,value=details.get(key,''))
                st.caption('Personal review checklist; saving it does not submit an application or verify eligibility.')
                updated['checklist']={item:st.checkbox(item,value=details.get('checklist',{}).get(item,False)) for item in CHECKLIST}
                updated['manual_answers']=st.text_area('Screening answers to copy manually (exact question and your answer)',value=details.get('manual_answers',''))
                updated['posting_description']=st.text_area('Full posting text (paste here if discovery could not retrieve it)',value=details.get('posting_description',''),height=220)
                if st.form_submit_button('Save application preparation'):
                    update_job(jid,application_details=json.dumps(updated));details=updated;st.success('Application preparation saved')
            done=sum(bool(details.get('checklist',{}).get(item)) for item in CHECKLIST)
            st.caption(f'{done} of {len(CHECKLIST)} review items saved as complete.')
        assessment=assess_job(dict(j,description=details.get('posting_description') or details.get('description','')),profile())
        with st.expander(f"Resume match: {assessment['match']} · {assessment['match_score']}/100"):
            st.text(assessment['match_reasons'])
            st.text(assessment['clearance_evidence'])
            st.text(assessment['experience_evidence'])
        st.caption('Use the fields below to prepare answers. Automation never submits on your behalf.')
        with st.form('review'):
            status=st.selectbox('Status',['Saved','In progress','Needs review','Ready','Applied','Rejected','Interview'],index=(['Saved','In progress','Needs review','Ready','Applied','Rejected','Interview'].index(j['status']) if j['status'] in ['Saved','In progress','Needs review','Ready','Applied','Rejected','Interview'] else 0))
            notes=st.text_area('Notes / complex prompts',value=j['notes'],height=160)
            answers=st.text_area('Additional answers (JSON object: exact field label → answer)',value=json.dumps(json.loads(j['answers']),indent=2),height=180)
            st.caption('These JSON answers may be autofilled. Keep eligibility, clearance and other certifications in the manual screening answers above.')
            if st.form_submit_button('Save review'):
                try:
                    a=json.loads(answers)
                    if not isinstance(a,dict):raise ValueError('Must be an object')
                    update_job(jid,status=status,notes=notes,answers=json.dumps(a));st.success('Saved')
                except Exception as e:st.error(f'Invalid JSON: {e}')
        docs=list((DATA/'documents').glob('*')) if (DATA/'documents').exists() else []
        chosen=st.selectbox('Resume to upload', ['None']+[f.name for f in docs])
        st.warning('Autofill is best-effort and may leave fields blank. Check every answer, attachment, and eligibility statement before submitting. CAPTCHA, login, MFA, and final submission remain in your browser.')
        workers=st.session_state.setdefault('application_workers',{})
        worker=workers.get(jid)
        running=worker is not None and worker.poll() is None
        control=DATA/'worker-control';status_file=control/f'{jid}.json'
        if status_file.exists():
            try:
                state=json.loads(status_file.read_text(encoding='utf-8')).get('state','')
                # Batch workers also accept repeat-fill commands after login.
                if time.time()-status_file.stat().st_mtime<10 and state.startswith(('Ready','Autofill complete','Needs manual review')):
                    running=True
            except (ValueError,OSError):pass
        st.caption('Account required? Use Accounts & Sessions first, or sign in in the application window. Then click Fill current browser page here. Repeat after navigating to the next form yourself. Applications on the same portal share a saved login session.')
        if st.button('Open browser and autofill',type='primary',disabled=running):
            cmd=[sys.executable,str(ROOT/'autofill.py'),'--job-id',str(jid),'--interactive']
            if chosen!='None':cmd+=['--resume',chosen]
            try:
                with (DATA/'autofill.log').open('a',encoding='utf-8') as logfile:
                    workers[jid]=subprocess.Popen(cmd,cwd=ROOT,stdout=logfile,stderr=subprocess.STDOUT,start_new_session=True)
                st.rerun()
            except Exception as e:st.error(f'Unable to launch: {e}')
        if status_file.exists():
            try:
                worker_status=json.loads(status_file.read_text(encoding='utf-8'))
                st.info(worker_status['state'])
                if worker_status.get('filled'):st.write('Filled fields: '+', '.join(worker_status['filled']))
                if worker_status.get('error'):st.error(worker_status['error'])
            except (ValueError,OSError):pass
        if st.button('Refresh browser status'):st.rerun()
        if st.button('Fill current browser page',disabled=not running):
            control.mkdir(parents=True,exist_ok=True)
            (control/f'{jid}.command').write_text('fill',encoding='utf-8')
            st.success('Requested autofill of the current page. Review the opened browser, then refresh status.')
        if st.button('Save session and close browser',disabled=not running):
            control.mkdir(parents=True,exist_ok=True)
            (control/f'{jid}.command').write_text('close',encoding='utf-8')
        if worker is not None and worker.poll() not in (None,0):
            st.error('Browser worker failed. It may be waiting on another window for the same portal; close that window and relaunch. See data/autofill.log for details.')
