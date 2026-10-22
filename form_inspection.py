"""Read-only form inventory. Independently implemented; no third-party code.

Only field metadata and empty/populated flags are returned, never input values.
The inventory is advisory: an alias match is not a promise of ATS compatibility.
"""
import re
from collections import Counter
from urllib.parse import urlsplit


MANUAL_QUESTION = re.compile(
    r'clearance|citizen|sponsor|authori[sz]|eligib|export|\bitar\b|\bear\b|'
    r'veteran|disab|gender|\brace\b|ethnic|social security|\bssn\b|birth|'
    r'certif|agree|consent|sexual|pronoun|hispanic|latino|visa|password', re.I)


def requires_manual_answer(label):
    return bool(MANUAL_QUESTION.search(label))


def portal_name(url):
    host = (urlsplit(url).hostname or '').lower()
    for suffix, name in [('.myworkdayjobs.com', 'Workday'), ('.greenhouse.io', 'Greenhouse'),
                         ('.lever.co', 'Lever'), ('.eightfold.ai', 'Eightfold'),
                         ('.icims.com', 'iCIMS')]:
        if host.endswith(suffix):
            return name
    if host == 'jobs.northropgrumman.com':
        return 'Eightfold'
    return 'Generic form'


def normalize_label(label):
    return re.sub(r'\s+', ' ', label).strip(' *:\t\n').casefold()


FIELD_METADATA = r'''() => Array.from(document.querySelectorAll(
    'input, textarea, select, [role="combobox"]'
)).filter(el => {
    const type = (el.type || '').toLowerCase();
    const style = getComputedStyle(el);
    return !['hidden', 'submit', 'button', 'reset', 'image'].includes(type)
        && el.getClientRects().length > 0 && style.visibility !== 'hidden'
        && style.display !== 'none';
}).slice(0, 200).map(el => {
    const labelText = node => {
        if (!node) return '';
        const copy = node.cloneNode(true);
        copy.querySelectorAll('input, textarea, select, button, [role="combobox"]').forEach(child => child.remove());
        return (copy.textContent || '').replace(/\s+/g, ' ').trim();
    };
    const labelledBy = (el.getAttribute('aria-labelledby') || '').split(/\s+/)
        .map(id => labelText(document.getElementById(id))).join(' ').trim();
    const linkedLabel = Array.from(el.labels || []).map(labelText).join(' ');
    const container = el.closest('[data-automation-id^="formField"], .form-group');
    const nearLabel = labelText(container?.querySelector('label'));
    const label = el.getAttribute('aria-label') || labelledBy || linkedLabel
        || nearLabel || el.getAttribute('placeholder') || '';
    const type = (el.getAttribute('type') || el.getAttribute('role') || el.tagName).toLowerCase();
    let populated = null;
    if (!['password', 'file'].includes(type)) {
        if (['checkbox', 'radio'].includes(type)) populated = !!el.checked;
        else if (el.tagName === 'SELECT') populated = el.value !== '';
        else if ('value' in el) populated = !!String(el.value).trim();
    }
    return {label: label.trim().slice(0, 180), type,
        required: !!el.required || el.getAttribute('aria-required') === 'true',
        populated, disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
        readonly: !!el.readOnly};
})'''


def inspect_page(page, applicant, aliases, answers=None):
    fields, warnings = [], []
    for index, frame in enumerate(page.frames):
        try:
            for row in frame.evaluate(FIELD_METADATA):
                fields.append(dict(row, frame=index, portal=portal_name(frame.url or page.url)))
                if len(fields) >= 200:
                    break
            if len(fields) >= 200:
                warnings.append('Inventory limited to 200 visible controls.')
                break
        except Exception:
            warnings.append(f'Could not inspect frame {index}; inspect it manually.')
    counts = Counter(normalize_label(row['label']) for row in fields if row['label'])
    lookup = {normalize_label(label): key for key, labels in aliases.items() for label in labels}
    answers = answers or {}
    custom = {normalize_label(label): value for label, value in answers.items()}
    for row in fields:
        label = normalize_label(row['label'])
        key = lookup.get(label)
        row['profile_field'] = ''
        if row['type'] == 'password':
            action = 'Sign in manually'
        elif requires_manual_answer(row['label']) or row['type'] in ('checkbox', 'radio'):
            action = 'Manual answer / certification'
        elif row['disabled'] or row['readonly']:
            action = 'Disabled / read-only'
        elif row['populated']:
            action = 'Already populated — review in browser'
        elif counts[label] > 1:
            action = 'Repeated label — review the correct section'
        elif row['type'] == 'file':
            action = 'Review attachment field in browser'
        elif row['type'] in ('select', 'combobox'):
            action = 'Select option manually'
        elif key and applicant.get(key):
            row['profile_field'] = key
            action = 'Profile value available; verify after autofill'
        elif label in custom and isinstance(custom[label], (str, int, float)) and str(custom[label]).strip():
            action = 'Custom answer available; verify after autofill'
        else:
            action = 'No saved answer — fill manually'
        row['action'] = action
        row['label'] = row['label'] or '(Unlabelled control)'
    return {'portal': portal_name(page.url), 'fields': fields, 'warnings': warnings,
            'required_blank': sum(row['required'] and row['populated'] is False for row in fields)}
