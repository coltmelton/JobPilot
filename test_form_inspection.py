"""Offline, real-browser checks for the read-only application field inventory."""
import json
import unittest

from playwright.sync_api import sync_playwright

from autofill import FIELDS, fill_current
from form_inspection import inspect_page, portal_name, requires_manual_answer


class FormInspectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()

    def test_inventory_reports_missing_fields_without_recording_values(self):
        self.page.set_content('''
            <label>First Name<input required></label>
            <label>Email<input type="email" value="private@example.test"></label>
            <label>Password<input type="password" value="do-not-record-me" required></label>
            <label>Active security clearance?<select required><option value="">Select</option><option>Yes</option></select></label>
            <label>Country<select required><option value="">Select</option></select></label>
            <label>Unfamiliar question<textarea required></textarea></label>
            <input type="hidden" value="hidden-token">
            <input aria-label="Hidden field" style="display:none">
            <label>I agree to the terms<input type="checkbox" required></label>
        ''')
        before = self.page.locator('input').evaluate_all('els => els.map(e => e.value)')
        report = inspect_page(self.page, {'first_name': 'Example'}, FIELDS)
        rows = {row['label']: row for row in report['fields']}
        self.assertEqual(len(rows), 7)
        self.assertTrue(rows['First Name']['action'].startswith('Profile value available'))
        self.assertEqual(rows['Password']['action'], 'Sign in manually')
        self.assertIsNone(rows['Password']['populated'])
        self.assertEqual(rows['Active security clearance?']['action'], 'Manual answer / certification')
        self.assertEqual(rows['Country']['action'], 'Select option manually')
        self.assertEqual(report['required_blank'], 5)
        self.assertEqual(before, self.page.locator('input').evaluate_all('els => els.map(e => e.value)'))
        serialized = json.dumps(report)
        for private in ('private@example.test', 'do-not-record-me', 'hidden-token'):
            self.assertNotIn(private, serialized)

    def test_iframes_repeated_labels_and_aria_labels(self):
        self.page.set_content('''<label>First Name<input></label>
            <iframe srcdoc="<label>First Name<input required></label>"></iframe>
            <span id="question">Why this role?</span><textarea aria-labelledby="question"></textarea>''')
        self.page.frames[1].wait_for_selector('input')
        report = inspect_page(self.page, {'first_name': 'Example'}, FIELDS, {'Why this role?': 'Private prepared answer'})
        first_names = [row for row in report['fields'] if row['label'] == 'First Name']
        self.assertEqual(len(first_names), 2)
        self.assertTrue(all(row['action'].startswith('Repeated label') for row in first_names))
        self.assertEqual({row['frame'] for row in first_names}, {0, 1})
        self.assertIn('Custom answer available', next(row['action'] for row in report['fields'] if row['label'] == 'Why this role?'))
        self.assertNotIn('Private prepared answer', json.dumps(report))

    def test_inventory_after_fill_and_manual_screening_stays_empty(self):
        self.page.set_content('<label>First Name<input required></label><label>Visa sponsorship<input required></label>')
        self.assertEqual(inspect_page(self.page, {'first_name': 'Example'}, FIELDS)['required_blank'], 2)
        fill_current(self.page, {'first_name': 'Example'}, {'Visa sponsorship': 'No'}, '')
        report = inspect_page(self.page, {'first_name': 'Example'}, FIELDS)
        self.assertEqual(report['required_blank'], 1)
        self.assertEqual(self.page.get_by_label('Visa sponsorship').input_value(), '')

    def test_platform_and_manual_question_detection(self):
        self.assertEqual(portal_name('https://kla.wd1.myworkdayjobs.com/Search'), 'Workday')
        self.assertEqual(portal_name('https://jobs.lever.co/palantir/123'), 'Lever')
        self.assertEqual(portal_name('https://jobs.northropgrumman.com/careers'), 'Eightfold')
        for label in ('Citizenship', 'Visa status', 'Security clearance', 'Pronouns', 'I consent', 'Work authorisation'):
            self.assertTrue(requires_manual_answer(label), label)
        self.assertFalse(requires_manual_answer('First name'))


if __name__ == '__main__':
    unittest.main()
