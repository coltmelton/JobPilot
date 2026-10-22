"""Offline browser fixtures for routine forms and conservative answer reuse."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright

import db
from form_intelligence import (fill_supported, value_for, next_step, blocking_fields, remember_answers,
                               review_page, entry_step, choose_resume, click_entry)
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

    def test_resume_method_preferred_over_manual_and_apply_handles_search(self):
        self.page.set_content('<label>Keywords<input type="search"></label><button>Apply</button>')
        self.assertEqual(entry_step(capture(self.page))['label'],'Apply')
        self.page.set_content('<a href="#manual">Apply manually</a><a href="#resume">Autofill with Resume</a>')
        self.assertEqual(entry_step(capture(self.page))['label'],'Autofill with Resume')
        self.assertIsNone(next_step(capture(self.page)), 'Never fall back to manual when resume autofill is offered')
        self.page.set_content('<label>First Name<input required></label><button>Apply</button>')
        self.assertIsNone(entry_step(capture(self.page)))
        self.page.set_content('<a href="https://fixture.test/start">Apply</a><a href="https://fixture.test/start">Apply</a>')
        self.assertIsNotNone(entry_step(capture(self.page)))
        self.page.set_content('<a href="https://fixture.test/one">Apply</a><a href="https://fixture.test/two">Apply</a>')
        self.assertIsNone(entry_step(capture(self.page)))

    def test_choose_resume_uses_explicit_then_profile_then_unique_resume(self):
        (self.documents/'cover-letter.txt').write_text('Letter')
        self.assertEqual(choose_resume('',{},self.documents),'')
        (self.documents/'resume.txt').write_text('Resume')
        self.assertEqual(choose_resume('',{},self.documents),'resume.txt')
        (self.documents/'resume-2.txt').write_text('Another resume')
        self.assertEqual(choose_resume('',{},self.documents),'')
        self.assertEqual(choose_resume('',{'matching':{'resume_file':'resume-2.txt'}},self.documents),'resume-2.txt')
        self.assertEqual(choose_resume('resume.txt',{},self.documents),'resume.txt')
        self.assertEqual(choose_resume('../outside.txt',{},self.documents),'')

    def test_upload_button_with_dynamically_created_file_input(self):
        self.page.set_content('''<button onclick="const input=document.createElement('input');input.type='file';input.onchange=()=>document.body.dataset.uploaded=input.files[0].name;document.body.append(input);input.click()">Upload resume</button>''')
        (self.documents/'resume.txt').write_text('Resume')
        view=capture(self.page)
        click_entry(self.page,view,entry_step(view),'resume.txt',self.documents)
        self.assertEqual(self.page.locator('body').get_attribute('data-uploaded'),'resume.txt')

    def test_delayed_search_options_scoped_to_active_list(self):
        self.page.set_content('''<div role="option">New York</div>
            <label>State<input role="combobox" aria-controls="states" required placeholder="Select" oninput="setTimeout(()=>document.querySelector('#states').innerHTML='<div role=option onclick=pick(this)>New York</div>',500)"></label>
            <div id="states" role="listbox"></div><script>function pick(el){document.querySelector('input').value=el.textContent;el.parentElement.hidden=true;document.body.dataset.selected='yes'}</script>''')
        fill_supported(self.page,{'state':'NY'},{},'',self.documents)
        self.assertEqual(self.page.locator('body').get_attribute('data-selected'),'yes')

    def test_readonly_custom_dropdown_is_selectable(self):
        self.page.set_content('''<label>Country<input role="combobox" readonly required placeholder="Select" aria-controls="countries" onclick="document.querySelector('#countries').hidden=false"></label>
            <div id="countries" hidden><div role="option" onclick="document.querySelector('input').value='United States';this.parentElement.hidden=true">United States</div></div>''')
        self.assertTrue(blocking_fields(capture(self.page)))
        fill_supported(self.page,{'country':'US'},{},'',self.documents)
        self.assertFalse(blocking_fields(capture(self.page)))
