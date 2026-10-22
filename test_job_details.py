"""Description fetching preserves boundaries, cache behaviour and profile privacy."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import job_details
from job_details import enrich_jobs, fetch_description
from matching import plain_text


class DescriptionTests(unittest.TestCase):
    def test_encoded_description_is_plain_text(self):
        text = plain_text('&lt;p&gt;Minimum &lt;strong&gt;5 years&lt;/strong&gt; of experience&lt;/p&gt;')
        self.assertNotIn('<', text)
        self.assertIn('5 years', text)
        self.assertEqual(plain_text(float('nan')), '')

    def test_workday_detail_url_and_plaintext(self):
        context = Mock()
        response = Mock(ok=True)
        response.json.return_value = {'jobPostingInfo': {'jobDescription': '<p>Python engineering experience</p>'}}
        context.request.get.return_value = response
        result = fetch_description(context, {'url': 'https://kla.wd1.myworkdayjobs.com/en-US/Search/job/Boston/Engineer_R1'})
        self.assertIn('Python', result)
        self.assertEqual(context.request.get.call_args.args[0], 'https://kla.wd1.myworkdayjobs.com/wday/cxs/kla/Search/job/Boston/Engineer_R1')

    def test_limit_cache_and_local_prioritisation(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(job_details, 'DATA', Path(folder)), patch.object(job_details, 'profile', return_value={'matching': {'text': 'Python software engineering'}}):
            browser = Mock()
            jobs = [{'url': 'https://example.com/jobs/1', 'title': 'Accounting'}, {'url': 'https://example.com/jobs/2', 'title': 'Python Software Engineer'}]
            text = 'Python software engineering. No security clearance required. ' * 4
            with patch.object(job_details, 'fetch_description', return_value=text) as fetch:
                enrich_jobs(browser, jobs, limit=1)
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(fetch.call_args.args[1]['title'], 'Python Software Engineer')
                self.assertNotIn('description', jobs[0])
                self.assertIn('limit reached', jobs[0]['description_status'])
                # A second call can use the cache with no additional network budget.
                again = [{'url': jobs[1]['url'], 'title': jobs[1]['title']}]
                enrich_jobs(browser, again, limit=0)
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(again[0]['description'], text)

    def test_failed_fetch_is_unknown_instead_of_empty_success(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(job_details, 'DATA', Path(folder)), patch.object(job_details, 'profile', return_value={}):
            job = {'url': 'https://example.com/jobs/1', 'title': 'Engineer'}
            with patch.object(job_details, 'fetch_description', side_effect=ValueError('HTTP 403')):
                enrich_jobs(Mock(), [job], limit=1)
            self.assertNotIn('description', job)
            self.assertEqual(job['description_status'], 'HTTP 403')


if __name__ == '__main__':
    unittest.main()
