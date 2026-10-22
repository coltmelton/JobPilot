"""Browser form mirror and bounded navigation for the in-app assistance inbox."""
import hashlib
import re
import uuid
from urllib.parse import urlsplit, urlunsplit

from form_inspection import portal_name,normalize_label,requires_manual_answer

DOM = r'''prefix => {
  const visible = el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
  const text = node => {
    if (!node) return '';
    const copy = node.cloneNode(true);
    copy.querySelectorAll('input,textarea,select,button,[role="combobox"]').forEach(n => n.remove());
    return (copy.textContent || '').replace(/\s+/g,' ').trim();
  };
  const label = el => el.getAttribute('aria-label') ||
    (el.getAttribute('aria-labelledby') || '').split(/\s+/).map(id => text(document.getElementById(id))).join(' ').trim() ||
    Array.from(el.labels || []).map(text).join(' ') ||
    text(el.closest('[data-automation-id^="formField"],.form-group')?.querySelector('label')) ||
    el.getAttribute('placeholder') || el.name || 'Unlabelled field';
  const fields = Array.from(document.querySelectorAll('input,textarea,select,[role="combobox"],[role="checkbox"],[role="radio"],button[aria-haspopup="listbox"]'))
    .filter(el => (visible(el) || el.type === 'file') && (!['hidden','submit','button','reset','image'].includes(el.type) || el.getAttribute('aria-haspopup') === 'listbox'))
    .slice(0,100).map((el,index) => {
      const id = prefix+'-f'+index;
      el.setAttribute('data-jobpilot-control',id);
      const type = (el.tagName === 'SELECT' ? 'select' : el.getAttribute('aria-haspopup') === 'listbox' ? 'combobox' : el.getAttribute('role') || el.getAttribute('type') || (el.tagName === 'TEXTAREA' ? 'textarea' : 'text')).toLowerCase();
      let populated = type === 'password' ? null : type === 'file' ? !!el.files?.length :
        ['checkbox','radio'].includes(type) ? (el.checked ?? el.getAttribute('aria-checked') === 'true') :
        type === 'combobox' && el.tagName !== 'INPUT' ? !!text(el).trim() :
        'value' in el ? !!String(el.value).trim() : !!text(el).trim();
      if (type === 'select' && /^\s*(?:select|choose|please select)/i.test(el.selectedOptions[0]?.textContent || '')) populated=false;
      if (type === 'combobox' && /^[\s\-–]*(?:select|choose|please select)/i.test(el.tagName === 'INPUT' ? el.value : text(el))) populated=false;
      if (type === 'radio' && el.name) populated = Array.from(document.querySelectorAll('input[type="radio"]')).some(other => other.name === el.name && other.form === el.form && other.checked);
      return {id,label:label(el).slice(0,180),type,populated,
        autocomplete:el.getAttribute('autocomplete') || '',
        required:!!el.required || el.getAttribute('aria-required') === 'true',
        disabled:!!el.disabled || el.getAttribute('aria-disabled') === 'true',readonly:!!el.readOnly,
        options:el.tagName === 'SELECT' ? Array.from(el.options).map((o,i) => ({index:i,label:o.textContent.trim().slice(0,160),disabled:o.disabled})).slice(0,200) : []};
    });
  const actions = Array.from(document.querySelectorAll('button,a,input[type="submit"],input[type="button"],[role="button"],[role="option"],[role="tab"]'))
    .filter(el => visible(el) && !el.disabled && el.getAttribute('aria-disabled') !== 'true')
    .map(el => ({el,label:(el.getAttribute('aria-label') || el.innerText || el.value || '').trim().replace(/\s+/g,' ')}))
    .filter(({el,label}) => label && label.length < 160 &&
      !/delete account|withdraw application|log out|sign out/i.test(label) &&
      (el.tagName !== 'A' || /apply|sign.?in|log.?in|create.*account|register|next|continue|application|autofill|upload.*(?:resume|cv)|without autofill|manually/i.test(label)))
    .slice(0,70).map(({el,label},index) => {
      const id=prefix+'-a'+index;el.setAttribute('data-jobpilot-action',id);
      return {id,label,role:el.getAttribute('role') || 'button',destination:el.tagName === 'A' ? el.href : ''};
    });
  const error_count = Array.from(document.querySelectorAll('[role="alert"],.error-message,[data-automation-id="errorMessage"]')).filter(el => visible(el) && text(el)).length;
  return {fields,actions,error_count};
}'''


def safe_url(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, '', ''))


def capture(page):
    view_id = uuid.uuid4().hex
    fields, actions, error_count = [], [], 0
    for index, frame in enumerate(page.frames):
        try:
            data = frame.evaluate(DOM, f'{view_id}-{index}')
            origin=urlsplit(frame.url).netloc or urlsplit(page.url).netloc
            fields.extend(dict(row, frame=index, origin=origin) for row in data['fields'])
            for row in data['actions']:
                destination=row.pop('destination','')
                actions.append(dict(row,frame=index,origin=origin,target=hashlib.sha256(destination.encode()).hexdigest() if destination else ''))
            error_count += data.get('error_count', 0)
        except Exception:
            continue
    return {'view_id': view_id, 'url': safe_url(page.url), 'portal': portal_name(page.url),
            'document': hashlib.sha256(page.url.encode()).hexdigest(), 'fields': fields, 'actions': actions, 'error_count': error_count}


def _control(page, view, item):
    if hashlib.sha256(page.url.encode()).hexdigest() != view['document']:
        raise ValueError('Page changed. Refresh the employer view.')
    frames = page.frames
    if item['frame'] >= len(frames):
        raise ValueError('Frame changed. Refresh the employer view.')
    attribute = 'data-jobpilot-control' if 'type' in item else 'data-jobpilot-action'
    locator = frames[item['frame']].locator(f'[{attribute}="{item["id"]}"]')
    if locator.count() != 1 or (item.get('type') != 'file' and not locator.is_visible()):
        raise ValueError('Control changed. Refresh the employer view.')
    return locator


def apply_changes(page, view, changes, documents_folder):
    fields = {field['id']: field for field in view['fields']}
    pending = []
    for key, value in changes.items():
        if key not in fields:
            raise ValueError('Unknown control. Refresh the employer view.')
        field = fields[key]
        if field['disabled'] or (field['readonly'] and field['type']!='combobox'):
            raise ValueError('This field cannot be edited.')
        locator = _control(page, view, field)
        pending.append((field, locator, value))
    # All selectors are validated before changing any field.
    for field, locator, value in pending:
        kind = field['type']
        if kind in ('checkbox', 'radio'):
            if not isinstance(value, bool):raise ValueError('Checkbox needs a yes/no value.')
            if locator.get_attribute('role') in ('checkbox','radio'):
                if (locator.get_attribute('aria-checked') == 'true') != value:locator.click()
            else:locator.set_checked(value)
        elif kind == 'select':
            if not isinstance(value, int) or value not in [option['index'] for option in field['options'] if not option['disabled']]:
                raise ValueError('Choose a listed option.')
            locator.select_option(index=value)
        elif kind == 'file':
            path = (documents_folder / str(value)).resolve()
            if path.parent != documents_folder.resolve() or not path.is_file():
                raise ValueError('Choose a file saved in Documents.')
            locator.set_input_files(str(path))
        elif kind == 'combobox':
            locator.click()
        else:
            locator.fill(str(value))


def click_action(page, view, action_id):
    action = next((action for action in view['actions'] if action['id'] == action_id), None)
    if not action:raise ValueError('Choose a visible employer action.')
    _control(page, view, action).click(timeout=10000)


def action_named(view, expression):
    matches = [action for action in view['actions'] if re.fullmatch(expression, action['label'], re.I)]
    return matches[0] if len(matches) == 1 else None


def page_state(page, view):
    # Only classify common site messages. Never persist the entire body text.
    body = page.locator('body').inner_text(timeout=5000).lower()
    headings = ' '.join(page.locator('h1,h2,[role="heading"]').all_text_contents()).lower()
    if re.search(r'application (?:has been )?(?:successfully )?submitted|thank you for applying|we (?:have )?received your application', body):
        return 'submitted'
    if re.search(r'no account (?:was )?found|account does not exist|user not found|email (?:is )?not registered', body):
        return 'account_required'
    captcha_frames=page.locator('iframe[src*="recaptcha"],iframe[src*="hcaptcha"]')
    if re.search(r'please complete.{0,25}captcha|captcha (?:failed|required)|verify you are human|checking your browser|unusual traffic|access denied', body) or any(captcha_frames.nth(index).is_visible() for index in range(captcha_frames.count())):
        return 'verification_required'
    if re.search(r'verification code|one.time (?:code|password)|two.factor|multi.factor|check your (?:email|inbox)', body):
        return 'verification_required'
    passwords = [field for field in view['fields'] if field['type'] == 'password' and not field['disabled']]
    if len(passwords) > 1 or passwords and re.search(r'create (?:an? )?account|register|sign up', headings):
        return 'account_required'
    if passwords or re.search(r'sign in|log in|login', headings) and any(field['type']=='email' or re.search(r'email|user\s*name',field['label'],re.I) for field in view['fields']):
        return 'login'
    return 'application'


def autofill_login(page, view, credentials):
    passwords = [field for field in view['fields'] if field['type'] == 'password' and not field['disabled']]
    emails = [field for field in view['fields'] if field['type'] == 'email' or re.search(r'email|user\s*name', field['label'], re.I)]
    if len(passwords) > 1 or len(emails) > 1 or not (passwords or emails):
        return False
    if any(field.get('origin') != urlsplit(page.url).netloc for field in emails+passwords):
        return False  # Never send a portal's saved credentials to a different iframe origin.
    changes = {emails[0]['id']: credentials['email']} if emails else {}
    if passwords:changes[passwords[0]['id']] = credentials['password']
    from db import DATA
    apply_changes(page, view, changes, DATA/'documents')
    button = action_named(view, r'sign\s*in|log\s*in|login')
    if not button:button = action_named(view, r'next|continue')
    if not button:return False
    click_action(page, view, button['id'])
    return True


def fill_known_selects(page,view,applicant,aliases):
    """Choose only exact, unique options for non-certification profile fields."""
    lookup={normalize_label(label):key for key,labels in aliases.items() for label in labels}
    changes={}
    for field in view['fields']:
        if field['type']!='select' or field['populated'] or field['disabled'] or requires_manual_answer(field['label']):continue
        key=lookup.get(normalize_label(field['label']))
        value=str(applicant.get(key,'')).strip() if key else ''
        if not value:continue
        matches=[option['index'] for option in field['options'] if not option['disabled'] and normalize_label(option['label'])==normalize_label(value)]
        if len(matches)==1:changes[field['id']]=matches[0]
    if changes:
        from db import DATA
        apply_changes(page,view,changes,DATA/'documents')
    return bool(changes)


def preview(page):
    masks = []
    for frame in page.frames:
        try:masks.extend(frame.locator('input[type="password"]').all())
        except Exception:pass
    return page.screenshot(type='jpeg', quality=65, full_page=False, mask=masks, timeout=10000)
