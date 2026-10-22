"""Conservative, review-first browser helper. Does not submit forms or defeat access controls."""
import argparse,json,time,re
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from db import DATA,get_job,profile
from browser_sessions import session_lock, state_path, save_state

FIELDS={
 'first_name':['First Name','Given Name','First name'],
 'last_name':['Last Name','Family Name','Last name'],
 'middle_name':['Middle Name','Middle name'],
 'preferred_name':['Preferred Name','Preferred name'],
 'email':['Email','Email Address','E-mail'],
 'phone':['Phone','Phone Number','Mobile Phone'],
 'city':['City'], 'state':['State','Province'],
 'address_line1':['Address Line 1','Street Address'],
 'address_line2':['Address Line 2','Apartment / Unit'],
 'postal_code':['ZIP Code','Postal Code'],
 'country':['Country'],
 'linkedin':['LinkedIn','LinkedIn Profile','LinkedIn URL'],
 'github':['GitHub','GitHub URL'],
 'website':['Website','Portfolio','Personal Website']
}
def fill(page,label,value):
    if not value:return False
    for loc in (page.get_by_label(label,exact=True),page.get_by_placeholder(label,exact=True)):
        try:
            if loc.count()==1 and loc.is_visible() and loc.is_enabled():
                tag=loc.evaluate('(el) => el.tagName.toLowerCase()')
                if tag in ('input','textarea'):
                    typ=loc.get_attribute('type') or ''
                    if typ.lower() in ('checkbox','radio','hidden','password','file','submit'):continue
                    existing=loc.input_value()
                    if not existing.strip():loc.fill(str(value));return True
        except Exception:pass
    return False

def fill_current(page, applicant, answers, resume):
    filled=[]
    for key,labels in FIELDS.items():
        for label in labels:
            if fill(page,label,applicant.get(key,'')):
                filled.append(label);break
    for label,value in answers.items():
        # Keep legal/eligibility certifications and demographic answers manual,
        # even when someone accidentally puts them in the custom-answer JSON.
        if re.search(r'clearance|citizen|sponsor|authoriz|eligib|export|itar|ear\b|veteran|disab|gender|race|ethnic|social security|ssn|birth|certif|agree|consent',label,re.I):
            continue
        if isinstance(value,(str,int,float)) and fill(page,label,str(value)):filled.append(label)
    if resume:
        path=(DATA/'documents'/resume).resolve()
        if path.parent==(DATA/'documents').resolve() and path.is_file():
            inputs=page.locator('input[type="file"]')
            if inputs.count()==1:inputs.set_input_files(str(path));filled.append('file upload')
    return filled


def run(jid,resume,interactive=False,wait_for_session=False):
    job=get_job(jid)
    if not job:raise ValueError('Unknown job')
    parsed=urlparse(job['url'])
    if parsed.scheme!='https' or not parsed.hostname:raise ValueError('Only https:// job URLs are allowed')
    p=profile();answers=json.loads(job['answers'])
    controls=DATA/'worker-control';controls.mkdir(parents=True,exist_ok=True)
    command=controls/f'{jid}.command'
    status=controls/f'{jid}.json'
    def report(state,**extra):
        payload={'state':state,**extra}
        temp=status.with_suffix('.tmp');temp.write_text(json.dumps(payload),encoding='utf-8');temp.replace(status)
    report('Waiting for portal session' if wait_for_session else 'Starting browser')
    with session_lock(job['url'],wait=wait_for_session), sync_playwright() as pw:
        command.unlink(missing_ok=True)
        saved=state_path(job['url'])
        browser=pw.chromium.launch(headless=False)
        context=browser.new_context(storage_state=str(saved) if saved.exists() else None)
        page=context.new_page()
        try:
            page.goto(job['url'],wait_until='domcontentloaded',timeout=60000)
            page.wait_for_timeout(1000)
            if not interactive:
                filled=fill_current(page,p,answers,resume)
                report('Autofill complete — review in browser',filled=filled)
            else:
                report('Ready — sign in / navigate, then click Fill current browser page')
            print('Sign in or register manually if needed. Review every answer and submit yourself.',flush=True)
            while browser.is_connected() and context.pages:
                try:
                    if command.exists():
                        action=command.read_text(encoding='utf-8').strip();command.unlink(missing_ok=True)
                        if action=='close':break
                        if action=='fill':
                            current=context.pages[-1]
                            filled=fill_current(current,profile(),json.loads(get_job(jid)['answers']),resume)
                            report('Autofill complete — review in browser',filled=filled)
                    save_state(context,job['url'])
                    status.touch()
                    context.pages[0].wait_for_timeout(1500)
                except Exception as exc:
                    if not browser.is_connected() or not context.pages:break
                    report('Needs manual review',error=str(exc));time.sleep(1)
        except Exception as exc:
            report('Browser error',error=str(exc));raise
        finally:
            try:save_state(context,job['url'])
            except Exception:pass
            browser.close()
            report('Browser closed — session retained')
if __name__=='__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('--job-id',type=int,required=True);parser.add_argument('--resume',default='')
    parser.add_argument('--interactive',action='store_true');parser.add_argument('--wait-for-session',action='store_true')
    args=parser.parse_args()
    try:
        run(args.job_id,args.resume,args.interactive,args.wait_for_session)
    except Exception as exc:
        folder=DATA/'worker-control';folder.mkdir(parents=True,exist_ok=True)
        (folder/f'{args.job_id}.json').write_text(json.dumps({'state':'Browser worker failed','error':str(exc)}),encoding='utf-8')
        raise
