"""Evidence-based form decisions using profile facts and explicitly remembered answers."""
import json
import re
import time
from pathlib import Path

from autofill import FIELDS
from form_inspection import normalize_label, requires_manual_answer
from workflow_browser import _control, capture


EXTRA_ALIASES = {
    'first_name': ['legal first name', 'given names'],
    'last_name': ['legal last name', 'surname'],
    'email': ['email address (personal)', 'confirm email', 'confirm email address'],
    'phone': ['telephone', 'mobile', 'telephone number', 'primary phone number'],
    'address_line1': ['address', 'address 1', 'street address line 1'],
    'address_line2': ['address 2', 'street address line 2'],
    'postal_code': ['zip', 'zip/postal code', 'postcode'],
    'state': ['state/province', 'state / province', 'region'],
    'country': ['country/region', 'country / region'],
    'website': ['portfolio url', 'portfolio website'],
    'skills': ['technical skills', 'technical skills / tools'],
    'professional_summary': ['professional summary'],
    'available_start': ['available start date', 'notice period'],
}
AUTOCOMPLETE = {'given-name':'first_name', 'family-name':'last_name', 'additional-name':'middle_name',
                'email':'email', 'tel':'phone', 'address-line1':'address_line1',
                'address-line2':'address_line2', 'address-level2':'city', 'address-level1':'state',
                'postal-code':'postal_code', 'country-name':'country', 'country':'country'}
COUNTRIES = {'us':'united states', 'usa':'united states', 'united states of america':'united states',
             'uk':'united kingdom', 'gb':'united kingdom', 'ca':'canada'}
# Profile state abbreviations commonly differ from the employer's full labels.
STATES = dict(pair.split(':') for pair in (
    'AL:Alabama|AK:Alaska|AZ:Arizona|AR:Arkansas|CA:California|CO:Colorado|CT:Connecticut|DE:Delaware|'
    'FL:Florida|GA:Georgia|HI:Hawaii|ID:Idaho|IL:Illinois|IN:Indiana|IA:Iowa|KS:Kansas|KY:Kentucky|'
    'LA:Louisiana|ME:Maine|MD:Maryland|MA:Massachusetts|MI:Michigan|MN:Minnesota|MS:Mississippi|'
    'MO:Missouri|MT:Montana|NE:Nebraska|NV:Nevada|NH:New Hampshire|NJ:New Jersey|NM:New Mexico|'
    'NY:New York|NC:North Carolina|ND:North Dakota|OH:Ohio|OK:Oklahoma|OR:Oregon|PA:Pennsylvania|'
    'RI:Rhode Island|SC:South Carolina|SD:South Dakota|TN:Tennessee|TX:Texas|UT:Utah|VT:Vermont|'
    'VA:Virginia|WA:Washington|WV:West Virginia|WI:Wisconsin|WY:Wyoming|DC:District of Columbia').split('|'))


def key_for(field):
    label = normalize_label(re.sub(r'\s*\(required\)\s*$', '', normalize_label(field['label']), flags=re.I))
    aliases = {normalize_label(label):key for key, labels in FIELDS.items() for label in labels}
    aliases.update({normalize_label(label):key for key, labels in EXTRA_ALIASES.items() for label in labels})
    key = aliases.get(label)
    if key:return key
    tokens = field.get('autocomplete', '').split()
    return AUTOCOMPLETE.get(tokens[-1]) if tokens else None


def reusable(field):
    return (field['type'] in ('text','textarea','email','tel','url','select','combobox','number')
            and not requires_manual_answer(field['label'])
            and not re.search(r'verification|one.time|passcode|otp|token|security|signature|initials|date of|salary|compensation|\bage\b',field['label'],re.I)
            and normalize_label(field['label']) != 'unlabelled field')


def value_for(field, applicant, answers):
    if not reusable(field):return None, None
    key = key_for(field)
    if key and applicant.get(key) not in (None, ''):return str(applicant[key]), key
    label = normalize_label(field['label'])
    known = {normalize_label(k):v for k,v in {**applicant.get('form_answers', {}), **answers}.items()}
    value = known.get(label)
    if isinstance(value, (str,int,float)) and str(value).strip():return str(value), None
    if label in ('full name', 'legal name') and applicant.get('first_name') and applicant.get('last_name'):
        return ' '.join(str(applicant[k]) for k in ('first_name','middle_name','last_name') if applicant.get(k)), None
    if label in ('country phone code','phone country code','country code'):
        phone = str(applicant.get('phone', '')).strip()
        if phone.startswith('+1'):return '+1', 'phone_code'
        country = normalize_label(str(applicant.get('country','')))
        if COUNTRIES.get(country, country) in ('united states','canada'):return '+1', 'phone_code'
    return None, None


def equivalent(actual, expected, key=None):
    a, b = normalize_label(actual), normalize_label(expected)
    if key == 'country':a,b = COUNTRIES.get(a,a),COUNTRIES.get(b,b)
    if key == 'state':a,b = STATES.get(a.upper(),a).casefold(),STATES.get(b.upper(),b).casefold()
    if key == 'phone_code':return bool(re.search(r'(?<!\d)\+1(?!\d)', actual)) and b == '+1'
    return a == b


def option_matches(options, value, key, applicant, label):
    matches = [option for option in options if equivalent(label(option),value,key)]
    if key == 'phone_code' and len(matches)>1:
        country = normalize_label(str(applicant.get('country','')))
        country = COUNTRIES.get(country,country)
        if country:matches=[option for option in matches if country in normalize_label(label(option))]
    return matches


def choose_resume(selected, applicant, documents):
    folder=Path(documents).resolve()
    preferred=selected or applicant.get('matching',{}).get('resume_file','')
    if preferred and preferred != 'None':
        path=(folder/preferred).resolve()
        return path.name if path.parent==folder and path.is_file() else ''
    files=[p for p in folder.glob('*') if p.is_file() and p.suffix.lower() in ('.pdf','.docx','.txt')
           and not re.search(r'cover[ _-]?letter|transcript|certificate',p.stem,re.I)]
    named=[p for p in files if re.search(r'resume|\bcv\b',p.stem,re.I)]
    candidates=named or files
    return candidates[0].name if len(candidates)==1 else ''


RESUME_METHOD = r'(?:auto\s*fill (?:with|using|from)|apply with|use) (?:a |your |my )?(?:resume|résumé|cv)'
UPLOAD_RESUME = r'upload (?:a |your |my )?(?:resume|résumé|cv)'
APPLY_ENTRY = r'apply|apply now|apply for (?:this )?(?:job|position)|start application|begin application'


def entry_step(view):
    """Ignore search filters on postings, but never treat a populated form as a posting."""
    methods=[a for a in view['actions'] if re.fullmatch(RESUME_METHOD,normalize_label(a['label']))]
    if methods:return methods[0]
    uploads=[a for a in view['actions'] if re.fullmatch(UPLOAD_RESUME,normalize_label(a['label']))]
    if uploads and not any(f['type']=='file' for f in view['fields']):return uploads[0]
    relevant=[f for f in view['fields'] if not f['disabled'] and not (
        f['type']=='search' or re.search(r'search|keyword|filter|job location',f['label'],re.I))]
    if relevant:return None
    choices=[a for a in view['actions'] if re.fullmatch(APPLY_ENTRY,normalize_label(a['label']))]
    same_target=choices and choices[0].get('target') and len({a.get('target') for a in choices})==1
    return choices[0] if len(choices)==1 or same_target else None


def click_entry(page,view,action,resume,documents):
    locator=_control(page,view,action)
    if re.fullmatch(UPLOAD_RESUME,normalize_label(action['label'])):
        path=(Path(documents)/resume).resolve()
        if path.parent != Path(documents).resolve() or not path.is_file():raise ValueError('Select a saved resume first.')
        with page.expect_file_chooser(timeout=4000) as chooser:
            locator.click(timeout=4000)
        chooser.value.set_files(str(path))
        wait_for_upload(page)
    else:locator.click(timeout=10000)


def wait_for_upload(page):
    """Allow visible ATS upload/parsing work to finish before advancing."""
    deadline=time.monotonic()+15
    page.wait_for_timeout(200)
    while time.monotonic()<deadline:
        busy=False
        for frame in page.frames:
            indicators=frame.locator('[aria-busy="true"],[role="progressbar"],[data-automation-id="loading"]')
            if any(item.is_visible() for item in indicators.all()):busy=True;break
        if not busy:return
        page.wait_for_timeout(300)


def select_combobox(page,view,field,value,key,applicant):
    locator=_control(page,view,field)
    frame=page.frames[field['frame']]
    locator.click(timeout=2500)
    controls=locator.get_attribute('aria-controls') or locator.get_attribute('aria-owns')
    # Portalled menus can live elsewhere in the document. Use their explicit ID when present.
    container=frame.locator('[id='+json.dumps(controls.split()[0])+']') if controls else frame.locator('body')
    options=container.get_by_role('option')
    editable=locator.evaluate('(el) => el.tagName === "INPUT" && !el.readOnly')
    if editable:
        # Search by the canonical name, even when the profile stores an abbreviation.
        search=COUNTRIES.get(normalize_label(value),value) if key=='country' else STATES.get(value.upper(),value) if key=='state' else value
        locator.fill(search,timeout=2500)
    deadline=time.monotonic()+3
    while True:
        candidates=[o for o in options.all() if o.is_visible() and o.is_enabled() and o.get_attribute('aria-disabled')!='true']
        chosen=option_matches(candidates,value,key,applicant,lambda o:o.inner_text())
        if len(chosen)==1:
            chosen[0].click(timeout=2500);return True
        if len(chosen)>1 or time.monotonic()>=deadline:
            locator.press('Escape',timeout=1000)
            if editable:locator.fill('',timeout=1000)
            return False
        page.wait_for_timeout(200)


def fill_supported(page, applicant, answers, resume, documents):
    """Re-inspect between controls; one changed widget must not invalidate all filling."""
    filled = []
    initial = capture(page)
    identities = [(f['frame'], f['label'], f['type']) for f in initial['fields']]
    for identity in dict.fromkeys(identities):
        view = capture(page)
        matches = [f for f in view['fields'] if (f['frame'],f['label'],f['type']) == identity]
        if len(matches) != 1:continue
        field = matches[0]
        if field['disabled'] or (field['readonly'] and field['type']!='combobox') or field['populated']:continue
        try:
            locator = _control(page,view,field)
            if field['type'] == 'file':
                uploads = [f for f in view['fields'] if f['type']=='file']
                is_resume = re.search(r'resume|curriculum vitae|\bcv\b',field['label'],re.I)
                other_doc = re.search(r'cover|letter|transcript|certificate',field['label'],re.I)
                path = (Path(documents) / resume).resolve() if resume else None
                if path and path.parent == Path(documents).resolve() and path.is_file() and not other_doc and (is_resume or len(uploads)==1):
                    locator.set_input_files(str(path),timeout=2500);wait_for_upload(page);filled.append(field['label'])
                continue
            value, key = value_for(field,applicant,answers)
            if value is None:continue
            if field['type'] == 'select':
                options = option_matches([o for o in field['options'] if not o['disabled']],value,key,applicant,lambda o:o['label'])
                if len(options) != 1:continue
                locator.select_option(index=options[0]['index'],timeout=2500)
            elif field['type'] == 'combobox':
                if not select_combobox(page,view,field,value,key,applicant):continue
            else:
                locator.fill(value,timeout=2500)
                locator.press('Tab',timeout=1000)
            filled.append(field['label'])
        except Exception:
            # Widgets can re-render each other. Re-inspect the remaining fields.
            continue
    return filled


def next_step(view):
    resume_offered=any(re.fullmatch(RESUME_METHOD,normalize_label(a['label'])) for a in view['actions'])
    patterns = (r'apply|apply now|apply for (?:this )?(?:job|position)|apply manually|apply without autofill|start application|begin application',) if not view['fields'] and not resume_offered else (
        r'(?:save\s*(?:and|&)\s*)?(?:next|continue)(?:\s+(?:application|step|to (?:next step|application|review)))?',)
    for pattern in patterns:
        candidates = [a for a in view['actions'] if re.fullmatch(pattern,normalize_label(a['label']))]
        if len(candidates)==1:return candidates[0]
    return None


def blocking_fields(view):
    return [f for f in view['fields'] if f['type']!='search' and f['required'] and not f['populated'] and not f['disabled'] and (not f['readonly'] or f['type']=='combobox')]


def review_page(page):
    headings=' '.join(page.locator('h1,h2,[role="heading"]').all_text_contents())
    return bool(re.search(r'review (?:your |the )?application|application (?:review|summary)|ready to submit|review and submit',headings,re.I))


def remember_answers(view, changes):
    import db
    applicant = db.profile()
    remembered = applicant.setdefault('form_answers', {})
    count = 0
    for field in view['fields']:
        value = changes.get(field['id'])
        if value is None or not reusable(field) or key_for(field):continue
        if field['type']=='select':value=next((o['label'] for o in field['options'] if o['index']==value),'')
        if isinstance(value,str) and value.strip():
            remembered[normalize_label(field['label'])]=value.strip();count+=1
    if count:db.save_profile(applicant)
    return count
