"""Offline regression checks for eligibility heuristics, parsing and login reuse."""
import json
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import db
import browser_sessions
from autofill import fill_current
from browser_sessions import session_key, session_lock, save_state, state_path
from matching import (assess_job, clearance_requirement, estimate_experience,
                      experience_requirement, extract_resume)
from streamlit.testing.v1 import AppTest


class MatchingTests(unittest.TestCase):
    def applicant(self, years=3):
        return {'clearance_level': 'None', 'matching': {'text': 'Python software automation SQL testing Linux. Software engineering and automation projects.', 'years_experience': years, 'experience_confirmed': True}}

    def test_active_clearance_is_a_mismatch(self):
        result = assess_job({'title': 'Software Engineer', 'description': 'Must possess an active Secret clearance. Two years of software experience.'}, self.applicant())
        self.assertEqual(result['match'], 'Clearance mismatch')
        self.assertLessEqual(result['match_score'], 10)

    def test_obtainable_or_preferred_clearance_is_not_excluded(self):
        for wording in ('Must have the ability to obtain and maintain a Secret clearance.',
                        'An active Secret clearance is preferred but not required.',
                        'Must have the ability to obtain an active Secret clearance.',
                        'No security clearance is required.'):
            result = assess_job({'title': 'Software Engineer', 'description': wording}, self.applicant())
            self.assertNotEqual(result['match'], 'Clearance mismatch', wording)

    def test_existing_clearance_plus_future_upgrade_remains_a_mismatch(self):
        for wording in ('Must have an active Top-Secret clearance at the time of application with the ability to obtain and maintain a TS/SCI',
                        'Applicants must have a current active in-scope U.S. Government issued Secret security clearance at the time of application',
                        'CLEARANCE REQUIRED FOR START: Yes\nCLEARANCE TYPE: Secret'):
            self.assertEqual(assess_job({'title': 'Engineer', 'description': wording}, self.applicant())['match'], 'Clearance mismatch', wording)

    def test_unknown_description_does_not_claim_fit(self):
        result = assess_job({'title': 'Python Software Engineer'}, self.applicant())
        self.assertEqual(result['match'], 'Needs review')
        self.assertEqual(result['clearance'], 'Not stated')
        self.assertIn('unverified', result['match_reasons'])

    def test_experience_requirements_and_preferred_sections(self):
        result = experience_requirement('Minimum qualifications\nThree years of engineering experience\nPreferred qualifications\n10 years of experience')
        self.assertEqual(result['minimum'], 3)
        self.assertEqual(result['preferred'], 10)
        result = experience_requirement("Bachelor's degree in a STEM discipline preferred from an accredited university and 12 years of related experience, or a Master's degree and 10 years experience, or a PhD and 8 years of experience")
        self.assertEqual(result['minimum'], 8)
        result = assess_job({'title': 'Engineer', 'description': 'Minimum 5+ years of software engineering experience.'}, self.applicant())
        self.assertEqual(result['experience_fit'], 'Above your experience')
        result = assess_job({'title': 'Engineer', 'description': "BS and 5 years of experience; MS and 2 years of experience"}, self.applicant())
        self.assertEqual(result['experience_fit'], 'Review degree / experience alternatives')

    def test_employment_dates_merge_overlaps_and_exclude_education(self):
        text = 'EDUCATION\nAugust 2016 - May 2020\nPROFESSIONAL EXPERIENCE\nEngineer Jan 2022 - Dec 2022\nWork study June 2022 - December 2023\nPROJECTS\nJanuary 2010 - Present'
        result = estimate_experience(text, date(2026, 10, 21))
        self.assertEqual(result['years'], 2.0)
        self.assertEqual(len(result['evidence']), 2)

    def test_day_dates_and_no_section(self):
        result = estimate_experience('EXPERIENCE\nIntern October 6, 2025 - October 6, 2026', date(2026, 10, 21))
        self.assertEqual(result['years'], 1.1)
        self.assertIsNone(estimate_experience('Education\n2020 - 2024')['years'])

    def test_docx_reader_and_empty_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'resume.docx'
            text = 'Software engineer with Python automation and SQL experience for engineering systems.'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('word/document.xml', f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
            self.assertEqual(extract_resume(path), text)
            path = Path(folder)/'empty.txt';path.write_text('empty')
            with self.assertRaises(ValueError):extract_resume(path)

    def test_portal_sessions_are_employer_scoped(self):
        self.assertEqual(session_key('https://kla.wd1.myworkdayjobs.com/Search/job/one'), session_key('https://kla.wd1.myworkdayjobs.com/en-US/Search/job/two'))
        self.assertNotEqual(session_key('https://kla.wd1.myworkdayjobs.com/Search'), session_key('https://sartorius.wd3.myworkdayjobs.com/Search'))
        self.assertNotEqual(session_key('https://jobs.lever.co/palantir/one'), session_key('https://jobs.lever.co/other/two'))

    def test_session_lock_releases_and_auth_state_can_be_reused(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as folder, patch.object(browser_sessions, 'DATA', Path(folder)):
            url = 'https://fixture.example/careers'
            with session_lock(url):
                with self.assertRaises(RuntimeError):
                    with session_lock(url):pass
            with session_lock(url):pass
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    context = browser.new_context()
                    context.add_cookies([{'name': 'session', 'value': 'offline-test', 'domain': 'fixture.example', 'path': '/'}])
                    save_state(context, url)
                    context.close()
                    reused = browser.new_context(storage_state=str(state_path(url)))
                    self.assertEqual(reused.cookies(url)[0]['value'], 'offline-test')
                    reused.close()
                finally:browser.close()

    def test_custom_screening_answers_stay_manual(self):
        with patch('autofill.fill', return_value=True) as fill:
            fill_current(Mock(), {}, {'Do you have an active clearance?': 'Yes', 'Why this role?': 'My own answer'}, '')
            labels = [call.args[1] for call in fill.call_args_list]
            self.assertNotIn('Do you have an active clearance?', labels)
            self.assertIn('Why this role?', labels)

    def test_resume_page_saves_reviewed_baseline_and_discovery_filters(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.multiple(db, DATA=root, DB=root/'jobs.sqlite3'):
                db.save_profile(self.applicant())
                app = AppTest.from_file('app.py', default_timeout=20).run()
                app.sidebar.radio[0].set_value('Resume & Matching').run()
                self.assertFalse(app.exception)
                next(field for field in app.number_input if field.label == 'Years of relevant experience for matching').set_value(2.5)
                next(button for button in app.button if button.label == 'Save matching profile').click().run()
                self.assertFalse(app.exception)
                self.assertEqual(db.profile()['matching']['years_experience'], 2.5)
                jobs = [{'company': 'Example', 'title': 'Software Engineer', 'url': 'https://example.com/jobs/'+str(index), 'location': '', 'source': 'https://example.com/careers', 'method': 'Page link', 'description': wording} for index, wording in enumerate(['Must possess an active Secret clearance.', 'Must be able to obtain a Secret clearance.'])]
                app.session_state['discovery_results'] = {'jobs': jobs, 'reports': []}
                app.sidebar.radio[0].set_value('Discover Jobs').run()
                self.assertFalse(app.exception)
                self.assertTrue(any('1 of 2 candidates remain' in field.value for field in app.caption))
                next(field for field in app.checkbox if field.label == 'Hide existing-clearance mismatches').uncheck().run()
                self.assertTrue(any('2 of 2 candidates remain' in field.value for field in app.caption))

    def test_all_pages_render_with_a_matching_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.multiple(db, DATA=root, DB=root/'jobs.sqlite3'):
                db.save_profile(self.applicant())
                db.save_job('Example', 'Software Engineer', 'https://example.com/jobs/1')
                app = AppTest.from_file('app.py', default_timeout=20).run()
                for page in app.sidebar.radio[0].options:
                    app.sidebar.radio[0].set_value(page).run()
                    self.assertFalse(app.exception, page)


if __name__ == '__main__':
    unittest.main()
