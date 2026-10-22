"""Read public careers pages without logging in, filling forms, or submitting data.

Run in a separate process because Streamlit's Windows event loop cannot always
launch Playwright. Results are candidates for human review, never auto-imported.
"""
import argparse
import json
import re
import sys
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

DEFAULT_SOURCES = [
    'https://www.anduril.com/open-roles?employmentType=full-time&employmentType=intern',
    'https://www.palantir.com/careers/open-positions/',
    'https://rtx.yello.co/app/collect/form/skcplB3_0DXSO3fy5M-o2A',
    'https://lockheedmartin.eightfold.ai/careers?location_radius_type=mi&location_distance_km=16&hl=en-US&query=Engineer%2C+Computer+Science%2C+Software&start=0&pid=996476572198&sort_by=relevance',
    'https://parkercareers.ttcportals.com/jobs/search',
    'https://kla.wd1.myworkdayjobs.com/Search',
    'https://www.sartorius.com/en/company/careers/vacancies-job-opportunities',
    'https://jobs.northropgrumman.com/careers?start=0&pid=1340074837112&sort_by=timestamp',
]


def clean_url(url):
    parts = urlsplit(url.strip())
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('Use an https:// careers URL without credentials.')
    # Keep identifiers and search filters, including repeated employmentType.
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith(('utm_', '_gl', '_ga', '_gcl', 'rx_'))]
    return urlunsplit(('https', parts.netloc.lower(), parts.path or '/', urlencode(query), ''))


def parse_sources(text):
    urls = re.findall(r'https://[^\s|<>"\u201c\u201d]+', text)
    return list(dict.fromkeys(clean_url(url.rstrip("',);")) for url in urls))


def company_for(url):
    host = urlsplit(url).hostname or ''
    for fragment, name in [('anduril', 'Anduril'), ('palantir', 'Palantir'),
                           ('rtx', 'RTX / Raytheon'), ('lockheedmartin', 'Lockheed Martin'),
                           ('parker', 'Parker Hannifin'), ('kla.', 'KLA'),
                           ('sartorius', 'Sartorius'), ('northropgrumman', 'Northrop Grumman')]:
        if fragment in host:
            return name
    return host


def is_job_url(url):
    p = urlsplit(url)
    path = p.path.rstrip('/')
    query = dict(parse_qsl(p.query))
    if query.get('pid'):
        return True
    return bool(re.search(r'/(?:job|jobs|position|positions|requisition|requisitions)/[^/]+', path, re.I)
                and not re.search(r'/(?:search|search-results|open-positions)$', path, re.I)
                or ('jobs.lever.co' in p.netloc and len(path.split('/')) >= 3)
                or ('greenhouse.io' in p.netloc and re.search(r'/\d+$', path)))


def job_locations(value):
    if isinstance(value, list):
        return '; '.join(filter(None, (job_locations(item) for item in value)))
    if isinstance(value, dict):
        address = value.get('address', value)
        if isinstance(address, dict):
            return ', '.join(str(address[k].get('name', '')) if isinstance(address[k], dict) else str(address[k]) for k in ('addressLocality', 'addressRegion', 'addressCountry') if address.get(k))
    return ''


def structured_jobs(value, base, company):
    """Walk JSON-LD graphs, including lists of JobPosting objects."""
    result = []
    if isinstance(value, list):
        for item in value:
            result.extend(structured_jobs(item, base, company))
    elif isinstance(value, dict):
        types = value.get('@type', [])
        if isinstance(types, str):
            types = [types]
        if 'JobPosting' in types:
            org = value.get('hiringOrganization') or {}
            posting_url = value.get('url') or (base if is_job_url(base) else '')
            if posting_url:
                result.append({'company': org.get('name', company) if isinstance(org, dict) else company,
                           'title': value.get('title', ''),
                           'url': urljoin(base, posting_url),
                           'location': job_locations(value.get('jobLocation')),
                           'description': value.get('description', ''),
                           'source': base, 'method': 'JobPosting metadata'})
        for key, child in value.items():
            if key != 'hiringOrganization' and isinstance(child, (dict, list)):
                result.extend(structured_jobs(child, base, company))
    return result


def deduplicate(jobs):
    unique = {}
    for job in jobs:
        try:
            url = clean_url(job['url'])
        except (ValueError, KeyError):
            continue
        if not str(job.get('title', '')).strip():
            continue
        # Workday/Lever apply URLs identify the same posting as the detail URL.
        url = re.sub(r'/apply/?$', '', url)
        identity_parts = urlsplit(url)
        pid = dict(parse_qsl(identity_parts.query)).get('pid')
        if not pid and ('eightfold.ai' in identity_parts.netloc or identity_parts.hostname == 'jobs.northropgrumman.com'):
            match = re.search(r'/job/(\d+)', identity_parts.path)
            pid = match.group(1) if match else None
        identity = (identity_parts.hostname, pid) if pid else url
        candidate = dict(job, url=url, title=str(job['title']).strip())
        if identity not in unique or unique[identity]['method'] == 'Page link':
            unique[identity] = candidate
    return list(unique.values())


def workday_jobs(request, source, max_pages, limit):
    p = urlsplit(source)
    tenant = p.hostname.split('.')[0]
    segments = [part for part in p.path.split('/') if part]
    site = segments[1] if segments and re.fullmatch(r'[a-z]{2}-[A-Z]{2}', segments[0]) and len(segments) > 1 else segments[0] if segments else ''
    if not site:
        return [], False
    # A supplied detail URL should stay scoped to that position, not the board.
    if '/job/' in p.path:
        return [], False
    endpoint = f'https://{p.netloc}/wday/cxs/{tenant}/{site}/jobs'
    jobs = []
    more = False
    query = dict(parse_qsl(p.query))
    facets = {}
    for key, value in parse_qsl(p.query):
        if key not in ('q', 'locationDistance', 'locationDistanceUnit'):
            facets.setdefault(key, []).append(value)
    for page_index in range(max_pages):
        response = request.post(endpoint, data={'appliedFacets': facets, 'limit': 20,
                                               'offset': page_index * 20, 'searchText': query.get('q', '')}, timeout=30000)
        if not response.ok:
            raise RuntimeError(f'Workday listings returned HTTP {response.status}')
        data = response.json()
        postings = data.get('jobPostings', [])
        for job in postings:
            external = job.get('externalPath', '')
            if external:
                jobs.append({'company': company_for(source), 'title': job.get('title', ''),
                             'url': f'https://{p.netloc}/{site}{external}',
                             'location': job.get('locationsText', ''), 'source': source,
                             'method': 'Workday public listings'})
        more = (page_index + 1) * 20 < data.get('total', 0) or len(jobs) > limit
        if not more or not postings or len(jobs) >= limit:
            break
    return jobs[:limit], more


def public_feed(request, source, limit):
    """Known public Greenhouse/Lever boards behind employer marketing pages."""
    host = urlsplit(source).hostname or ''
    path = urlsplit(source).path.rstrip('/')
    jobs = []
    # Do not replace individual posting links with an entire board.
    if host in ('anduril.com', 'www.anduril.com') and path == '/open-roles':
        response = request.get('https://boards-api.greenhouse.io/v1/boards/andurilindustries/jobs', timeout=30000)
        if not response.ok:
            raise RuntimeError(f'Greenhouse HTTP {response.status}')
        for job in response.json().get('jobs', []):
            jobs.append({'company': 'Anduril', 'title': job['title'], 'url': job['absolute_url'],
                         'location': (job.get('location') or {}).get('name', ''),
                         'source': source, 'method': 'Greenhouse public listings'})
        note = 'Public board read; marketing-page employment filters are not applied by this feed. Filter and review candidates below.'
    elif host in ('palantir.com', 'www.palantir.com') and path == '/careers/open-positions':
        response = request.get('https://api.lever.co/v0/postings/palantir?mode=json', timeout=30000)
        if not response.ok:
            raise RuntimeError(f'Lever HTTP {response.status}')
        for job in response.json():
            jobs.append({'company': 'Palantir', 'title': job['text'], 'url': job['hostedUrl'],
                         'description': '\n'.join([job.get('descriptionPlain', ''), *[item.get('text', '') + '\n' + item.get('content', '') for item in job.get('lists', [])], job.get('additionalPlain', '')]),
                         'location': (job.get('categories') or {}).get('location', ''),
                         'source': source, 'method': 'Lever public listings'})
        note = 'Public board read.'
    else:
        return [], ''
    # Apply the result cap after local resume prioritisation, so an alphabetical
    # board doesn't spend the entire scan budget on unrelated early titles.
    from db import profile
    from matching import assess_job, skills_in
    applicant = profile()
    if applicant.get('matching', {}).get('text'):
        resume_skills = set(skills_in(applicant['matching']['text']))
        def priority(job):
            assessment = assess_job(job, applicant)
            title_overlap = len(set(skills_in(job['title'])) & resume_skills)
            if assessment['match'] == 'Seniority needs review':
                title_overlap -= 2
            return (assessment['match'] != 'Clearance mismatch', title_overlap, assessment['match_score'])
        jobs.sort(key=priority, reverse=True)
        note += ' Prioritised locally using your resume before applying the result limit.'
    if len(jobs) > limit:
        note += f' Partial results: showing first {limit} of {len(jobs)}; increase the result limit to see more.'
    return jobs[:limit], note


def collect_page(page, source):
    jobs = []
    links = []
    company = company_for(source)
    for frame in page.frames:
        try:
            for raw in frame.locator('script[type="application/ld+json"]').all_text_contents():
                try:
                    jobs.extend(structured_jobs(json.loads(raw), page.url, company))
                except (ValueError, TypeError):
                    pass
            links.extend(frame.locator('a[href]').evaluate_all('''elements => elements.map(a => ({
                url: a.href, title: (a.innerText || a.getAttribute('aria-label') || '').trim()
            }))'''))
        except Exception:
            continue
    for link in links:
        if is_job_url(link['url']) and link['title'] and link['title'].lower() not in ('apply', 'apply now', 'learn more', 'view all jobs'):
            lines = [line.strip() for line in link['title'].splitlines() if line.strip()]
            jobs.append({'company': company, 'title': lines[0], 'url': link['url'],
                         'location': lines[1] if len(lines)>1 else '', 'source': source, 'method': 'Page link'})
    return jobs, links


def scan_source(browser, source, max_pages=3, limit=100, manual_wait=0):
    source = clean_url(source)
    company = company_for(source)
    report = {'source': source, 'company': company, 'status': '', 'count': 0}
    if urlsplit(source).hostname.endswith('yello.co') and '/collect/form/' in source:
        report['status'] = 'Talent / event registration form, not a job board. Open manually; use https://careers.rtx.com/global/en/search-results for vacancies.'
        return [], report
    context = browser.new_context()
    try:
        try:
            jobs, note = public_feed(context.request, source, limit)
            if jobs:
                report.update(count=len(jobs), status=note)
                return deduplicate(jobs), report
        except Exception as exc:
            report['status'] = f'Public feed unavailable ({exc}); tried rendered page. '
        if urlsplit(source).hostname in ('sartorius.com', 'www.sartorius.com') and '/vacancies-job-opportunities' in source:
            board = 'https://sartorius.wd3.myworkdayjobs.com/sartoriuscareers'
            try:
                jobs, more = workday_jobs(context.request, board, max_pages, limit)
                if jobs:
                    for job in jobs:
                        job['source'] = source
                    report.update(count=len(jobs), status='Linked Sartorius Workday board read. ' + ('Partial results: page/result limit reached.' if more else ''))
                    return deduplicate(jobs), report
            except Exception as exc:
                report['status'] += f'Linked Workday board unavailable ({exc}). '
        if urlsplit(source).hostname.endswith('myworkdayjobs.com'):
            try:
                jobs, more = workday_jobs(context.request, source, max_pages, limit)
                if jobs:
                    report.update(count=len(jobs), status='Partial results: page/result limit reached.' if more else 'Public listings read.')
                    return deduplicate(jobs), report
            except Exception as exc:
                report['status'] = f'Workday feed unavailable ({exc}); tried rendered page. '
        page = context.new_page()
        page.set_default_timeout(2500)
        response = page.goto(source, wait_until='domcontentloaded', timeout=45000)
        page.wait_for_timeout(manual_wait * 1000 if manual_wait else 2500)
        body = page.locator('body').inner_text(timeout=5000).lower()
        if (not manual_wait and response and response.status in (401, 403, 429)) or any(text in body for text in ('verify you are human', 'checking your browser', 'just a moment...', 'access denied')):
            report['status'] += 'Access restricted or verification required. Open this source manually, or try a visible scan to complete consent/verification yourself. No restriction was bypassed.'
            return [], report
        jobs = []
        seen = set()
        exhausted = False
        for index in range(max_pages):
            # Scroll to trigger lazy-loaded cards; no form fields are changed.
            for _ in range(3):
                page.mouse.wheel(0, 1800)
                page.wait_for_timeout(400)
            found, links = collect_page(page, source)
            jobs.extend(found)
            jobs = deduplicate(jobs)
            if len(jobs) >= limit:
                break
            # Follow a public ATS board linked by a marketing careers page.
            if not jobs and index == 0:
                boards = [link['url'] for link in links
                          if any(host in (urlsplit(link['url']).hostname or '')
                                 for host in ('jobs.lever.co', 'boards.greenhouse.io', 'job-boards.greenhouse.io', 'myworkdayjobs.com'))]
                if boards:
                    board = next((url for url in boards if not is_job_url(url)), boards[0])
                    if 'myworkdayjobs.com' in (urlsplit(board).hostname or ''):
                        board = re.sub(r'/login/?$', '', board)
                        try:
                            found, more = workday_jobs(context.request, board, max_pages, limit)
                            if found:
                                for job in found:
                                    job['company'] = company
                                    job['source'] = source
                                report.update(count=len(found), status='Linked public Workday board read. ' + ('Partial results: page/result limit reached.' if more else ''))
                                return found, report
                        except Exception:
                            pass
                    page.goto(board, wait_until='domcontentloaded', timeout=45000)
                    page.wait_for_timeout(2000)
                    found, _ = collect_page(page, source)
                    jobs.extend(found)
            signature = tuple(job['url'] for job in jobs)
            if signature in seen:
                break
            seen.add(signature)
            next_button = page.get_by_role('button', name=re.compile(r'^(next(?: page)?|load more|show more(?: jobs)?)$', re.I))
            next_link = page.get_by_role('link', name=re.compile(r'^next(?: page)?(?:\s*[»›→])?$', re.I))
            control = next_button if next_button.count() == 1 else next_link
            if control.count() != 1 or not control.is_visible() or not control.is_enabled():
                # Eightfold boards also expose public pagination through start.
                # Preserve the supplied query/location and selected-position ID.
                parsed = urlsplit(source)
                if parsed.path.rstrip('/') == '/careers' and ('eightfold.ai' in parsed.netloc or parsed.hostname == 'jobs.northropgrumman.com') and len(found) >= 10:
                    if index < max_pages - 1:
                        query = dict(parse_qsl(parsed.query))
                        query['start'] = str(int(query.get('start', '0')) + (index + 1) * 10)
                        page.goto(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), '')), wait_until='domcontentloaded', timeout=45000)
                        page.wait_for_timeout(2000)
                        continue
                    break
                exhausted = True
                break
            if index < max_pages - 1:
                control.click()
                page.wait_for_timeout(1500)
        jobs = deduplicate(jobs)[:limit]
        for job in jobs:
            job['source'] = source
        report['count'] = len(jobs)
        report['status'] += ('Candidate links found; review titles and application URLs. ' +
                             ('More pages may exist; increase scan limits or refine the source URL.' if not exhausted or len(jobs) >= limit else 'Only accessible rendered links were inspected; completeness is not guaranteed.')) if jobs else 'No job links found. The page may require consent, login, a different search, or a site adapter. Open it manually; no jobs imported.'
        return jobs, report
    except Exception as exc:
        report['status'] = f'Could not read this source: {exc}'
        return [], report
    finally:
        context.close()


def discover(sources, max_pages=3, limit=100, headed=False, detail_limit=20):
    from playwright.sync_api import sync_playwright
    jobs, reports = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed)
        try:
            for source in sources:
                found, report = scan_source(browser, source, max_pages, limit, manual_wait=30 if headed else 0)
                jobs.extend(found)
                reports.append(report)
                print(f"{report['company']}: {report['count']} candidates", file=sys.stderr, flush=True)
        finally:
            browser.close()
    # Description enrichment uses public pages only, never a saved account.
    result = {'jobs': deduplicate(jobs), 'reports': reports}
    if detail_limit:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                from job_details import enrich_jobs
                enrich_jobs(browser, result['jobs'], detail_limit)
            finally:
                browser.close()
    return result


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument('--sources-file', help='UTF-8 text containing career URLs')
    source_group.add_argument('--enrich-file', help='Existing discovery JSON whose descriptions should be fetched')
    parser.add_argument('--output', required=True)
    parser.add_argument('--pages', type=int, default=3)
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--headed', action='store_true', help='Visible browser; wait 30 seconds per rendered source for manual consent/verification')
    parser.add_argument('--details', type=int, default=20, help='Maximum additional public descriptions to fetch (0–200)')
    args = parser.parse_args()
    from pathlib import Path
    if not 1 <= args.pages <= 20 or not 1 <= args.limit <= 1000 or not 0 <= args.details <= 200:
        parser.error('pages must be 1–20; limit 1–1000; details 0–200')
    if args.enrich_file:
        from playwright.sync_api import sync_playwright
        from job_details import enrich_jobs
        result = json.loads(Path(args.enrich_file).read_text(encoding='utf-8'))
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                enrich_jobs(browser, result['jobs'], args.details)
            finally:
                browser.close()
    else:
        sources = parse_sources(Path(args.sources_file).read_text(encoding='utf-8'))
        if not sources:
            parser.error('No https:// URLs found')
        result = discover(sources, args.pages, args.limit, args.headed, args.details)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
