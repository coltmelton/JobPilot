"""Fetch public descriptions for queued jobs without opening applicant accounts."""
import argparse
import json

from db import get_jobs, get_job, update_job
from job_details import enrich_jobs


def analyze(limit=20, job_id=None):
    from playwright.sync_api import sync_playwright
    jobs = [get_job(job_id)] if job_id else get_jobs()
    jobs = [job for job in jobs if job]
    for job in jobs:
        details = json.loads(job.get('application_details') or '{}')
        job['description'] = details.get('posting_description') or details.get('description', '')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            enrich_jobs(browser, jobs, limit)
        finally:
            browser.close()
    for job in jobs:
        # Reload after the network calls so concurrent notes/checklist edits survive.
        current = get_job(job['id'])
        if not current:
            continue
        details = json.loads(current.get('application_details') or '{}')
        for key in ('description', 'description_status', 'description_fetched_at'):
            if key in job:
                details[key] = job[key]
        update_job(job['id'], application_details=json.dumps(details))
    print(f'Finished: {sum(bool(job.get("description")) for job in jobs)} of {len(jobs)} jobs have description text.', flush=True)


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--job-id', type=int)
    args = parser.parse_args()
    if not 1 <= args.limit <= 200:
        parser.error('limit must be 1–200')
    analyze(args.limit, args.job_id)
