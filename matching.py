"""Local, explainable resume matching. No external model or resume upload."""
import hashlib
import html
import re
import zipfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree


SKILLS = ['python', 'sql', 'excel', 'power bi', 'tableau', 'javascript', 'typescript',
          'react', 'java', 'c++', 'c#', 'linux', 'git', 'docker', 'kubernetes', 'aws',
          'azure', 'terraform', 'matlab', 'simulink', 'solidworks', 'autocad', 'sap',
          'erp', 'salesforce', 'supply chain', 'logistics', 'inventory', 'procurement',
          'manufacturing', 'quality', 'lean', 'six sigma', 'project management',
          'data analysis', 'data analytics', 'machine learning', 'statistics',
          'software', 'automation', 'testing', 'embedded', 'firmware', 'systems engineering',
          'robotics', 'calibration', 'instrumentation', 'metrology', 'unity',
          'mechanical', 'electrical', 'cybersecurity', 'networking', 'operations',
          'leadership', 'customer service', 'business intelligence', 'api', 'rest']


def plain_text(value):
    if not isinstance(value, str):
        return ''
    value = html.unescape(html.unescape(value or ''))
    value = re.sub(r'<(?:br|/p|/li|/div|/h[1-6])\b[^>]*>', '\n', value, flags=re.I)
    return html.unescape(re.sub(r'<[^>]+>', ' ', value)).strip()


def extract_resume(path):
    path = Path(path)
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError('Use a resume smaller than 20 MB.')
    if path.suffix.lower() == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(''):
            raise ValueError('This PDF is encrypted. Use an unlocked copy or paste its text.')
        text = '\n'.join(page.extract_text() or '' for page in reader.pages[:30])
    elif path.suffix.lower() == '.docx':
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo('word/document.xml')
            if info.file_size > 10 * 1024 * 1024:
                raise ValueError('DOCX content is too large.')
            root = ElementTree.fromstring(archive.read(info))
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        text = '\n'.join(''.join(p.itertext()) for p in root.findall('.//w:p', ns))
    elif path.suffix.lower() == '.txt':
        text = path.read_text(encoding='utf-8-sig')
    else:
        raise ValueError('Choose a PDF, DOCX, or UTF-8 TXT resume.')
    if len(text.strip()) < 50:
        raise ValueError('Not enough readable text. For scanned PDFs, paste the resume text below or use a text-based PDF.')
    return text.strip()


def skills_in(text):
    return [skill for skill in SKILLS if re.search(r'(?<![\w+#])' + re.escape(skill) + r'(?![\w+#])', text, re.I)]


MONTHS = {name.lower(): index for index, name in enumerate(
    ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 1)}
DATE_TOKEN = r'(?:(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+(?:\d{1,2},?\s+)?\d{4}|\d{1,2}/\d{4}|(?:19|20)\d{2})'
DATE_RANGE = re.compile(r'(' + DATE_TOKEN + r')\s*(?:[-–—]|\bto\b)\s*(' + DATE_TOKEN + r'|Present|Current|Now)', re.I)


def month_number(token, today, end=False):
    if token.lower() in ('present', 'current', 'now'):
        return today.year * 12 + today.month - 1
    if '/' in token:
        month, year = map(int, token.split('/'))
        if not 1 <= month <= 12:
            raise ValueError('Invalid month')
    elif token.isdigit():
        year, month = int(token), 12 if end else 1
    else:
        month, year = MONTHS[token[:3].lower()], int(token[-4:])
    return year * 12 + month - 1


def estimate_experience(text, today=None):
    """Union of employment date ranges; never add overlapping jobs twice.

    Restrict to an explicitly named experience section so education/project dates
    don't become employment. Estimates include internships/co-ops and need review.
    """
    today = today or date.today()
    active = False
    months = set()
    evidence = []
    for line in text.splitlines():
        heading = re.sub(r'[^a-z ]', '', line.lower()).strip()
        if heading in ('experience', 'work experience', 'professional experience', 'employment', 'employment history', 'work history', 'relevant experience'):
            active = True
            continue
        if heading in ('education', 'projects', 'skills', 'technical skills', 'certifications', 'activities', 'leadership', 'awards', 'summary'):
            active = False
        if not active:
            continue
        for match in DATE_RANGE.finditer(line):
            try:
                start = month_number(match[1], today)
                end = min(month_number(match[2], today, end=True), today.year * 12 + today.month - 1)
                if 0 <= end - start <= 12 * 60:
                    months.update(range(start, end + 1))
                    evidence.append(match[0])
            except (ValueError, KeyError):
                continue
    return {'years': round(len(months) / 12, 1) if evidence else None,
            'evidence': evidence, 'note': 'Calendar estimate from employment dates; includes internships/co-ops and part-time work, merges overlaps, and is not a full-time-equivalent calculation. Year-only dates are approximate. Confirm relevant experience yourself.'}


def resume_fingerprint(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def clearance_requirement(text):
    normalized = re.sub(r'\bu\.s\.', 'us', text.lower())
    sentences = re.split(r'[\n!?;]+|\.\s+', normalized)
    evidence = []
    active = False
    obtainable = False
    none = False
    for sentence in sentences:
        sentence = sentence.strip()
        if not re.search(r'clearance|ts/sci|top secret', sentence):
            continue
        evidence.append(sentence)
        if re.search(r'no\s+(?:security\s+)?clearance\s+(?:is\s+)?required|clearance\s*:\s*(?:none|not required)', sentence):
            none = True
            continue
        if re.search(r'preferred|nice to have|desired|not required', sentence):
            continue
        obtain = re.search(r'(?:ability|able|eligible|willingness)\s+to\s+(?:obtain|secure)|obtain.{0,35}(?:after|following).{0,20}(?:hire|start)|clearance.{0,30}(?:sponsor|sponsorship)', sentence)
        existing = re.search(r'\b(?:active|current|existing)\b.{0,85}(?:clearance|ts/sci)|(?:clearance|ts/sci).{0,65}\b(?:active|current|prior to start|at (?:the )?(?:time of (?:hire|application)|start))\b|clearance required for start\s*:\s*yes', sentence)
        must_have = re.search(r'must (?:already |currently )?(?:hold|possess|have)\s+(?!(?:the |an? )?(?:ability|capability|eligibility))[^.;]{0,90}(?:clearance|ts/sci)', sentence)
        if must_have or existing and (not obtain or existing.start() < obtain.start()):
            active = True
        elif obtain:
            obtainable = True
    status = 'Existing clearance required' if active else 'Ability to obtain — review timing' if obtainable else 'No clearance required' if none else 'Review clearance wording' if evidence else 'Not stated'
    return status, evidence[:4]


def experience_requirement(text):
    # Keep preferred requirements separate; preserve degree substitution alternatives.
    required, preferred, evidence = [], [], []
    preferred_section = False
    text = re.sub(r'\b(one|two|three|four|five|six|seven|eight|nine|ten)\b', lambda m: str(['one','two','three','four','five','six','seven','eight','nine','ten'].index(m[0].lower())+1), text, flags=re.I)
    pattern = re.compile(r'(\d{1,2})(?:\s*[-–]\s*\d{1,2})?\s*\+?\s*(?:years?|yrs)\b[’\']?(?:\s+of)?(?:\s+[\w/-]+){0,6}\s+experience', re.I)
    for line in re.split(r'[\n;]+', text):
        if re.search(r'preferred qualifications|desired qualifications|nice to have', line, re.I):
            preferred_section = True
        if re.search(r'basic qualifications|minimum qualifications|required qualifications', line, re.I):
            preferred_section = False
        for match in pattern.finditer(line):
            # A preferred degree does not make the years later in that line optional.
            optional = re.search(r'prefer|desired|nice to have', line[match.end():match.end()+35], re.I) or re.match(r'\s*[-*•]?\s*(?:preferred|desired|nice to have)',line,re.I)
            target = preferred if preferred_section or optional else required
            target.append(int(match[1]))
            evidence.append(line.strip()[:400])
    return {'minimum': min(required) if required else None, 'preferred': min(preferred) if preferred else None,
            'alternatives': len(set(required)) > 1, 'evidence': evidence[:5]}


def assess_job(job, applicant):
    resume = applicant.get('matching', {})
    resume_text = resume.get('text', '')
    candidate_skills = set(skills_in(resume_text + ' ' + applicant.get('skills', '')))
    description = plain_text(job.get('description', ''))
    text = job.get('title', '') + '\n' + description
    job_skills = set(skills_in(text))
    matched = sorted(job_skills & candidate_skills)
    missing = sorted(job_skills - candidate_skills)
    clearance, clearance_evidence = clearance_requirement(text)
    requirement = experience_requirement(description)
    years = resume.get('years_experience')
    if not isinstance(years, (int, float)) or years < 0:
        years = None
    blockers, concerns, reasons = [], [], []
    no_clearance = applicant.get('clearance_level', 'Not provided') == 'None'
    if no_clearance and clearance == 'Existing clearance required':
        blockers.append('Posting explicitly asks for an existing clearance; your profile says none.')
    elif clearance == 'Ability to obtain — review timing':
        concerns.append('Posting allows obtaining a clearance, but timing and eligibility need verification.')
    elif clearance in ('Not stated', 'Review clearance wording'):
        concerns.append('Clearance requirement needs review.')
    if not description:
        concerns.append('Full description unavailable: requirements are unverified.')
    experience_status = 'Not stated' if requirement['minimum'] is None else 'Review experience'
    if requirement['minimum'] is not None and years is not None:
        if years < requirement['minimum']:
            experience_status = 'Above your experience'
            concerns.append(f"Posting mentions at least {requirement['minimum']} years; your baseline is {years:g}. Check relevant experience and education substitutions.")
        else:
            experience_status = 'Within your experience baseline'
            reasons.append(f"Experience baseline {years:g} years meets the lowest parsed {requirement['minimum']}-year requirement; verify discipline and degree alternatives.")
    elif years is None:
        concerns.append('Confirm your years of relevant experience in Resume & Matching.')
    if requirement['alternatives']:
        concerns.append('Multiple experience requirements or degree substitutions detected; review the full posting.')
        if experience_status.startswith('Within'):
            experience_status = 'Review degree / experience alternatives'
    if not resume.get('experience_confirmed'):
        concerns.append('Experience baseline has not been confirmed by you.')
    if matched:
        reasons.append('Resume skill overlap: ' + ', '.join(matched))
    if missing:
        concerns.append('Posting skills not detected in resume: ' + ', '.join(missing))
    seniority_review = bool(re.search(r'\b(senior|sr\.?|lead)\b', job.get('title', ''), re.I) and (years is None or years < 4)
        or re.search(r'\b(principal|staff|director|manager|head)\b', job.get('title', ''), re.I) and (years is None or years < 5))
    if seniority_review:
        concerns.append('Senior/leadership title may be a stretch; check the actual requirements.')
    overlap = len(matched) / max(1, len(job_skills))
    score = round(40 + 40 * overlap + (10 if experience_status.startswith('Within') else -20 if experience_status == 'Above your experience' else 0) + (5 if clearance == 'No clearance required' else 0))
    if not candidate_skills:
        score = min(score, 40)
    if not description:
        score = min(score, 45)
    if seniority_review and requirement['minimum'] is None:
        score = min(score, 55)
    if blockers:
        score = min(score, 10)
    label = 'Clearance mismatch' if blockers else 'Experience stretch' if experience_status == 'Above your experience' else 'Seniority needs review' if seniority_review and requirement['minimum'] is None else 'Potential match' if matched and description else 'Needs review'
    return {'match_score': max(0, min(100, score)), 'match': label, 'clearance': clearance,
            'experience_fit': experience_status, 'minimum_years': requirement['minimum'],
            'matched_skills': ', '.join(matched), 'missing_skills': ', '.join(missing),
            'match_reasons': '\n'.join(reasons + blockers + concerns),
            'clearance_evidence': '\n'.join(clearance_evidence),
            'experience_evidence': '\n'.join(requirement['evidence']),
            'description_status': job.get('description_status') if isinstance(job.get('description_status'), str) else 'Available' if description else 'Not fetched'}
