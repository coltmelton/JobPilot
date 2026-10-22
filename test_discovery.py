"""Deterministic discovery checks; no real employer network requests."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import db
from discovery import (DEFAULT_SOURCES, clean_url, deduplicate, is_job_url,
                       parse_sources, public_feed, scan_source, structured_jobs,
                       workday_jobs)
from streamlit.testing.v1 import AppTest


class DiscoveryTests(unittest.TestCase):
    def test_user_style_link_list_preserves_filters(self):
        sources = parse_sources('"' + ' | '.join(DEFAULT_SOURCES) + '"')
        self.assertEqual(len(sources), 8)
        self.assertIn('employmentType=full-time&employmentType=intern', sources[0])
        self.assertIn('pid=996476572198', sources[3])
        self.assertEqual(parse_sources(sources[0] + '\n' + sources[0]), [sources[0]])

    def test_tracking_removed_but_job_identifiers_kept(self):
        self.assertEqual(clean_url('https://example.com/careers?pid=123&_gl=abc&utm_source=x&query=software'),
                         'https://example.com/careers?pid=123&query=software')
        with self.assertRaises(ValueError):
            clean_url('https://user:password@example.com/')

    def test_board_is_not_a_posting(self):
        for url in DEFAULT_SOURCES[:3] + DEFAULT_SOURCES[4:7]:
            self.assertFalse(is_job_url(url), url)
        self.assertTrue(is_job_url('https://jobs.lever.co/palantir/abc-123'))
        self.assertTrue(is_job_url('https://example.com/jobs/123-engineer'))

    def test_jsonld_and_eightfold_duplicate(self):
        source = DEFAULT_SOURCES[3]
        jobs = structured_jobs({'@graph': [{'@type': 'JobPosting', 'title': 'Software Engineer',
            'jobLocation': {'address': {'addressLocality': 'Boston', 'addressCountry': {'name': 'US'}}}}]}, source, 'Lockheed Martin')
        jobs.append(dict(jobs[0], url='https://lockheedmartin.eightfold.ai/careers/job/996476572198', method='Page link'))
        self.assertEqual(len(deduplicate(jobs)), 1)
        self.assertEqual(jobs[0]['location'], 'Boston, US')
        self.assertEqual(structured_jobs({'@type': 'JobPosting', 'title': 'No detail URL'}, 'https://example.com/careers', 'Employer'), [])

    def test_workday_pages_and_filters(self):
        request = Mock()
        response = Mock(ok=True)
        response.json.return_value = {'total': 50, 'jobPostings': [
            {'title': 'Engineer', 'externalPath': '/job/Boston/Engineer_R1', 'locationsText': 'Boston'}]}
        request.post.return_value = response
        jobs, more = workday_jobs(request, 'https://kla.wd1.myworkdayjobs.com/en-US/Search?q=engineer&workerSubType=intern', 2, 100)
        self.assertEqual(request.post.call_count, 2)
        self.assertTrue(more)
        self.assertEqual(jobs[0]['url'], 'https://kla.wd1.myworkdayjobs.com/Search/job/Boston/Engineer_R1')
        body = request.post.call_args.kwargs['data']
        self.assertEqual(body['offset'], 20)
        self.assertEqual(body['searchText'], 'engineer')
        self.assertEqual(body['appliedFacets'], {'workerSubType': ['intern']})

    def test_public_feeds_and_limits(self):
        request = Mock()
        response = Mock(ok=True)
        response.json.return_value = {'jobs': [
            {'title': 'Intern', 'absolute_url': 'https://example.com/jobs/1', 'location': {'name': 'Boston'}},
            {'title': 'Engineer', 'absolute_url': 'https://example.com/jobs/2'}]}
        request.get.return_value = response
        jobs, note = public_feed(request, DEFAULT_SOURCES[0], 1)
        self.assertEqual(len(jobs), 1)
        self.assertIn('Partial results', note)
        self.assertIn('filters are not applied', note)
        self.assertEqual(jobs[0]['location'], 'Boston')

    def test_registration_form_is_not_a_job(self):
        browser = Mock()
        jobs, report = scan_source(browser, DEFAULT_SOURCES[2])
        self.assertEqual(jobs, [])
        self.assertIn('registration form', report['status'])
        browser.new_context.assert_not_called()

    def test_rendered_page_pagination_and_metadata(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            original_context = browser.new_context
            def context_with_fixture():
                context = original_context()
                def serve(route):
                    if 'page=2' in route.request.url:
                        html = '<a href="/jobs/2">Test Engineer</a>'
                    else:
                        html = '''<script type="application/ld+json">{"@type":"JobPosting","title":"Software Engineer","url":"/jobs/1","jobLocation":{"address":{"addressLocality":"Boston"}}}</script>
                        <a href="/jobs/1">Software Engineer</a><a href="?page=2">Next</a>'''
                    route.fulfill(status=200, content_type='text/html', body=html)
                context.route('**/*', serve)
                return context
            try:
                with patch.object(browser, 'new_context', side_effect=context_with_fixture):
                    jobs, report = scan_source(browser, 'https://fixture.example/careers', max_pages=2)
                self.assertEqual(len(jobs), 2)
                self.assertEqual(jobs[0]['location'], 'Boston')
                self.assertEqual(report['count'], 2)
                self.assertEqual({job['title'] for job in jobs}, {'Software Engineer', 'Test Engineer'})
            finally:
                browser.close()

    def test_discovery_review_and_import(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.multiple(db, DATA=root, DB=root/'jobs.sqlite3'):
                app = AppTest.from_file('app.py', default_timeout=15).run()
                app.session_state['discovery_results'] = {
                    'reports': [{'source': 'https://example.com/careers', 'status': 'Read', 'count': 1}],
                    'jobs': [{'company': 'Example', 'title': 'Software Engineer', 'url': 'https://example.com/jobs/1', 'location': 'Boston', 'source': 'https://example.com/careers', 'method': 'Page link'}]}
                app.sidebar.radio[0].set_value('Discover Jobs').run()
                self.assertFalse(app.exception)
                self.assertEqual(len(db.get_jobs()), 0)
                # Simulate selecting the first row in Streamlit's data editor.
                editor_keys = [key for key in app.session_state.keys() if key.startswith('discovery_review_')]
                self.assertEqual(len(editor_keys), 1)
                app.session_state[editor_keys[0]] = {'edited_rows': {0: {'Select': True}}, 'added_rows': [], 'deleted_rows': []}
                next(button for button in app.button if button.label == 'Import selected postings').click().run()
                self.assertFalse(app.exception)
                self.assertEqual(len(db.get_jobs()), 1)
                next(button for button in app.button if button.label == 'Import selected postings').click().run()
                self.assertEqual(len(db.get_jobs()), 1)


if __name__ == '__main__':
    unittest.main()
