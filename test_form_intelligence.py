"""Offline browser fixtures for routine forms and conservative answer reuse."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright

import db
from form_intelligence import fill_supported, value_for, next_step, blocking_fields, remember_answers, review_page
from workflow_browser import capture


class IntelligenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start()
        cls.browser=cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.pw.stop()

    def setUp(self):
        self.page=self.browser.new_page();self.addCleanup(self.page.close)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.documents=Path(self.temp.name)

    def test_starred_labels_autocomplete_and_country_state_equivalence(self):
        self.page.set_content('''<label>First Name*<input required></label>
            <label>Family details<input autocomplete="family-name" required></label>
            <label>State / Province<select required><option value="">Select</option><option>New York</option></select></label>
            <label>Country/Region<select required><option value="">Select</option><option>United States of America</option></select></label>''')
        filled=fill_supported(self.page,{'first_name':'Example','last_name':'Applicant','state':'NY','country':'US'},{},'',self.documents)
        self.assertEqual(len(filled),4)
        self.assertEqual(self.page.get_by_label('First Name*').input_value(),'Example')
        self.assertEqual(blocking_fields(capture(self.page)),[])

    def test_custom_button_and_searchable_combobox(self):
        self.page.set_content('''<label id="country-label">Country*</label>
            <button aria-labelledby="country-label" aria-haspopup="listbox" aria-required="true" onclick="document.querySelector('#choices').hidden=false">Select</button>
            <div id="choices" hidden><div role="option" onclick="document.querySelector('button').textContent=this.textContent;this.parentElement.hidden=true">United States</div></div>
            <label>State<input type="text" role="combobox" aria-required="true" onclick="document.querySelector('#states').hidden=false"></label>
            <div id="states" hidden><div role="option" onclick="document.querySelector('input').value=this.textContent;this.parentElement.hidden=true">New York</div></div>''')
        fill_supported(self.page,{'country':'US','state':'NY'},{},'',self.documents)
        view=capture(self.page)
        self.assertEqual([f['type'] for f in view['fields']],['combobox','combobox'])
        self.assertEqual(blocking_fields(view),[])
        self.assertEqual(self.page.locator('input').input_value(),'New York')

    def test_radio_group_and_readonly_do_not_block(self):
        self.page.set_content('''<label>Yes<input type="radio" name="choice" required checked></label>
            <label>No<input type="radio" name="choice" required></label>
            <label>Employer field<input readonly required></label>''')
        self.assertFalse(blocking_fields(capture(self.page)))

    def test_iframe_and_resume_not_cover_letter(self):
        self.page.set_content('<iframe></iframe><label>Cover letter<input type="file"></label><label>Resume<input type="file" hidden></label>')
        self.page.frames[1].set_content('<label>First Name*<input required></label>')
        (self.documents/'resume.txt').write_text('Test resume',encoding='utf-8')
        fill_supported(self.page,{'first_name':'Example'},{},'resume.txt',self.documents)
        self.assertEqual(self.page.frames[1].get_by_label('First Name*').input_value(),'Example')
        self.assertEqual(self.page.get_by_label('Resume').evaluate('(el) => el.files.length'),1)
        self.assertEqual(self.page.get_by_label('Cover letter').evaluate('(el) => el.files.length'),0)

    def test_memory_reuses_routine_answer_but_excludes_secrets_and_certifications(self):
        self.page.set_content('''<label>How Did You Hear About Us?*<select required><option value="">Select</option><option>Company website</option></select></label>
            <label>Clearance<input></label><label>Verification code<input></label><label>Password<input type="password"></label>''')
        view=capture(self.page)
        changes={f['id']:1 if f['type']=='select' else 'Do not store' for f in view['fields']}
        with patch.object(db,'DATA',self.documents):
            self.assertEqual(remember_answers(view,changes),1)
            applicant=db.profile()
            self.assertNotIn('Do not store',str(applicant))
            fill_supported(self.page,applicant,{},'',self.documents)
            self.assertEqual(self.page.get_by_label('How Did You Hear About Us?*').input_value(),'Company website')
            self.assertEqual(self.page.get_by_label('Clearance').input_value(),'')

    def test_ambiguous_fields_options_and_submission_are_not_guessed(self):
        self.page.set_content('''<label>First Name<input></label><label>First Name<input></label>
            <label>Country<select><option value="">Select</option><option>United States</option><option>United States</option></select></label>
            <button>Submit application</button>''')
        self.assertEqual(fill_supported(self.page,{'first_name':'Example','country':'US'},{},'',self.documents),[])
        self.assertIsNone(next_step(capture(self.page)))
        for label in ('Are you authorized to work?', 'Clearance', 'Consent', 'Password'):
            self.assertEqual(value_for({'type':'text','label':label},{'form_answers':{label:'Yes'}},{}),(None,None))

    def test_phone_code_uses_country_to_resolve_shared_dial_code(self):
        self.page.set_content('''<label>Country Phone Code*<select required><option value="">Select</option><option>Canada (+1)</option><option>United States (+1)</option></select></label>''')
        fill_supported(self.page,{'country':'US'},{},'',self.documents)
        self.assertEqual(self.page.locator('select').input_value(),'United States (+1)')

    def test_common_step_wording(self):
        self.page.set_content('<label>Email<input></label><button>Save &amp; Continue</button>')
        self.assertEqual(next_step(capture(self.page))['label'],'Save & Continue')

    def test_final_apply_on_review_page_requires_review(self):
        self.page.set_content('<h1>Review your application</h1><button>Apply now</button>')
        self.assertTrue(review_page(self.page))
