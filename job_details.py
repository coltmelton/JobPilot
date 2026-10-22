"""Bounded public description fetching, with a local cache and no applicant data."""
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit, parse_qsl

from db import DATA, profile
from matching import plain_text, skills_in


def fetch_description(context, job):
    url = job['url']
    parts = urlsplit(url)
    host = parts.hostname or ''
    if host in ('jobs.lever.co', 'jobs.eu.lever.co'):
        segments = [part for part in parts.path.split('/') if part]
        if len(segments) < 2:
            raise ValueError('Use an individual Lever posting URL.')
        api_host = 'api.eu.lever.co' if host.startswith('jobs.eu.') else 'api.lever.co'
        response = context.request.get(f'https://{api_host}/v0/postings/{segments[0]}/{segments[1]}', timeout=25000)
        if not response.ok:
            raise ValueError(f'Public description returned HTTP {response.status}')
        data = response.json()
        return plain_text('\n'.join([data.get('descriptionPlain', ''), *[item.get('text', '') + '\n' + item.get('content', '') for item in data.get('lists', [])], data.get('additionalPlain', '')]))
    if host.endswith('greenhouse.io'):
        segments = [part for part in parts.path.split('/') if part]
        job_id = dict(parse_qsl(parts.query)).get('gh_jid') or segments[-1]
        board = segments[0]
        response = context.request.get(f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}', timeout=25000)
        if not response.ok:
            raise ValueError(f'Public description returned HTTP {response.status}')
        return plain_text(response.json().get('content', ''))
    if host.endswith('.myworkdayjobs.com'):
        segments = [part for part in parts.path.split('/') if part]
        if re.fullmatch(r'[a-z]{2}-[A-Z]{2}', segments[0]):
            segments.pop(0)
        site = segments.pop(0)
        response = context.request.get(f'https://{host}/wday/cxs/{host.split(".")[0]}/{site}/' + '/'.join(segments), timeout=25000)
        if not response.ok:
            raise ValueError(f'Public description returned HTTP {response.status}')
        return plain_text(response.json().get('jobPostingInfo', {}).get('jobDescription', ''))
    page = context.new_page()
    try:
        response = page.goto(url, wait_until='domcontentloaded', timeout=30000)
        page.wait_for_timeout(1000)
        if response and response.status >= 400:
            raise ValueError(f'Page returned HTTP {response.status}')
        for raw in page.locator('script[type="application/ld+json"]').all_text_contents():
            try:
                def description(value):
                    if isinstance(value, list):
                        return next((found for item in value if (found := description(item))), '')
                    if isinstance(value, dict):
                        types = value.get('@type', [])
                        if 'JobPosting' in types:
                            return plain_text(value.get('description', ''))
                        return next((found for item in value.values() if isinstance(item, (list, dict)) and (found := description(item))), '')
                    return ''
                found = description(json.loads(raw))
                if found:
                    return found
            except (ValueError, TypeError):
                pass
        # Only extract a job-specific container, never an entire search results page.
        for selector in ('[data-automation-id="jobPostingDescription"]', '[itemprop="description"]', '.job-description', '.job-description-container', '[data-testid="job-description"]'):
            locator = page.locator(selector)
            if locator.count() == 1:
                text = locator.inner_text(timeout=3000)
                if len(text) > 100:
                    return text
        raise ValueError('No job-specific description found; open the posting or paste its text in Review & Launch.')
    finally:
        page.close()


def enrich_jobs(browser, jobs, limit=20):
    folder = DATA / 'job-cache'
    folder.mkdir(parents=True, exist_ok=True)
    context = browser.new_context()
    fetched = 0
    try:
        applicant = profile()
        resume_text = applicant.get('matching', {}).get('text', '') + ' ' + applicant.get('skills', '')
        resume_skills = set(skills_in(resume_text))
        # Spend bounded fetches on the most relevant-looking titles first.
        # Applicant text is only used locally; requests contain posting URLs only.
        ordered = sorted(jobs, key=lambda job: len(set(skills_in(job.get('title', ''))) & resume_skills), reverse=True)
        for job in ordered:
            if isinstance(job.get('description'), str) and job['description'].strip():
                job.setdefault('description_status', 'Available')
                continue
            job.pop('description', None)
            cache = folder / (hashlib.sha256(job['url'].encode()).hexdigest() + '.json')
            if cache.exists() and time.time() - cache.stat().st_mtime < 24 * 3600:
                try:
                    cached = json.loads(cache.read_text(encoding='utf-8'))
                    job.update(cached)
                    continue
                except (ValueError, OSError):
                    pass
            if fetched >= limit:
                job.setdefault('description_status', 'Not fetched: description limit reached')
                continue
            fetched += 1
            try:
                text = fetch_description(context, job)
                if len(text.strip()) < 100:
                    raise ValueError('Description was empty or too short to assess.')
                detail = {'description': text[:100000], 'description_status': 'Available',
                          'description_fetched_at': datetime.now(timezone.utc).isoformat()}
                job.update(detail)
                cache.write_text(json.dumps(detail), encoding='utf-8')
            except Exception as exc:
                job['description_status'] = str(exc)
            print(f'Description {fetched}/{limit}: {job["title"]}', flush=True)
    finally:
        context.close()
    return jobs
