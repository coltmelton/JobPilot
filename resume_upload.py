"""Per-application upload guard, including attachments retained after input resets."""
import re


ATTACHMENT_CHECK = r'''filename => {
  const visible = el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
  const resume = /resume|résumé|curriculum vitae|\bcv\b/i;
  const other = /cover[ -]?letter|transcript|certificate/i;
  const name = filename.toLowerCase();
  const scope = el => {
    const region = el.closest('section,fieldset,[data-automation-id^="formField"],.form-group');
    return (region?.querySelector('legend,h2,h3,label')?.textContent || '')+' '+(region?.getAttribute('data-automation-id') || '');
  };
  const otherScope = el => other.test(scope(el)) && !resume.test(scope(el));
  for (const input of document.querySelectorAll('input[type="file"]')) {
    const label = [...(input.labels || [])].map(l => l.textContent).join(' ') || input.getAttribute('aria-label') || input.name || '';
    if (input.files?.length && !other.test(label) && (resume.test(label) || [...input.files].some(f => f.name.toLowerCase() === name))) return true;
  }
  const candidates = document.querySelectorAll('[data-automation-id*="attachment" i],[data-automation-id*="uploaded" i],[data-testid*="attachment" i],.uploaded-file,.file-name,.attachment,a[download],[role="status"]');
  for (const el of candidates) {
    if (!visible(el)) continue;
    const text = (el.textContent || '').trim();
    if (/failed|error|rejected|not uploaded|uploading|processing/i.test(text)) continue;
    if (otherScope(el)) continue;
    const structural = el.getAttribute('role') !== 'status';
    if (structural && (name && text.toLowerCase().includes(name) || (resume.test(scope(el)) || resume.test(text)) && /\.(pdf|docx?|txt)\b/i.test(text))) return true;
    if (resume.test(text) && /uploaded|attached|on file|upload complete/i.test(text)) return true;
  }
  // Some ATSs show only a filename plus a Remove/Replace control after upload.
  for (const el of document.querySelectorAll('span,p,li,a')) {
    if (!name || !visible(el) || otherScope(el) || (el.textContent || '').trim().toLowerCase() !== name) continue;
    const box = el.parentElement;
    if (box && /remove|replace|delete/i.test(box.textContent) && box.querySelector('button,a,[role="button"]')) return true;
  }
  return false;
}'''


def is_resume_field(field, fields):
    label=field['label']
    if re.search(r'cover|letter|transcript|certificate',label,re.I):return False
    return bool(re.search(r'resume|résumé|curriculum vitae|\bcv\b',label,re.I) or len([f for f in fields if f['type']=='file'])==1)


def attachment_present(page, resume):
    for frame in page.frames:
        try:
            if frame.evaluate(ATTACHMENT_CHECK,resume):return True
        except Exception:
            continue
    return False


def upload_blocked(page, resume, state):
    if attachment_present(page,resume):
        state['status']='attached'
    return state.get('status') in ('attached','attempted')


def mark_attempt(state):
    # Set before touching the widget: an uncertain network result must not cause a duplicate.
    state['status']='attempted'


def mark_result(page,resume,state):
    if attachment_present(page,resume):state['status']='attached'
