"""Offline workflow checks. All browser requests are fulfilled by test fixtures."""
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import db
import browser_sessions
import credential_vault as vault
import workflow_store as store
from workflow_browser import capture, apply_changes, click_action, page_state,autofill_login,fill_known_selects
from workflow_worker import run_batch
from playwright.sync_api import sync_playwright as real_playwright


@unittest.skipUnless(os.name == 'nt', 'Windows DPAPI is required')
class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.patchers=[patch.multiple(db,DATA=self.root,DB=self.root/'jobs.sqlite3'),patch.object(vault,'VAULT_DIR',self.root/'private'),patch.object(browser_sessions,'DATA',self.root)]
        for patcher in self.patchers:patcher.start();self.addCleanup(patcher.stop)
        db.save_profile({'first_name':'Example','email':'candidate@example.test'})

    def add_job(self,url='https://fixture.test/start'):
        return db.save_job('Fixture employer','Engineer',url)

    def test_credentials_encrypted_and_scoped(self):
        vault.save_credentials('candidate@example.test','test-only-passphrase')
        self.assertIsNone(vault.get_credentials('https://fixture.test/login'))
        vault.allow_shared('https://fixture.test/login')
        self.assertEqual(vault.get_credentials('https://fixture.test/another')['password'],'test-only-passphrase')
        self.assertIsNone(vault.get_credentials('https://unapproved.test/login'))
        vault.save_credentials('override@example.test','different-test-password','https://fixture.test/')
        self.assertEqual(vault.get_credentials('https://fixture.test/login')['email'],'override@example.test')
        for path in (self.root/'private').glob('*'):
            data=path.read_bytes()
            self.assertNotIn(b'test-only-passphrase',data)
            self.assertNotIn(b'different-test-password',data)
        vault.forget_credentials('https://fixture.test/')
        self.assertIsNone(vault.get_credentials('https://fixture.test/login'))

    def test_commands_and_screenshots_are_encrypted_and_stale_views_rejected(self):
        jid=self.add_job();rid=store.create_run([jid]);task=store.tasks(rid)[0]
        store.update_task(task['id'],'needs_information','Input needed',{'view_id':'current'},b'private-test-preview')
        with self.assertRaises(ValueError):store.send_command(task['id'],'fields','old',changes={'secret':'test-secret'})
        store.send_command(task['id'],'fields','current',changes={'secret':'test-secret'})
        self.assertNotIn(b'test-secret',db.DB.read_bytes())
        self.assertNotIn(b'private-test-preview',db.DB.read_bytes())
        self.assertEqual(store.pop_command(task['id'])['changes']['secret'],'test-secret')
        self.assertIsNone(store.pop_command(task['id']))
        self.assertEqual(store.screenshot_bytes(task['id']),b'private-test-preview')

    def test_active_batch_blocks_reset_and_job_ids_are_not_reused(self):
        first=self.add_job();rid=store.create_run([first])
        with self.assertRaises(ValueError):db.clear_job_queue()
        with self.assertRaises(ValueError):store.create_run([first])
        store.finish_run(rid,'stopped')
        db.clear_job_queue()
        second=self.add_job('https://fixture.test/new')
        self.assertGreater(second,first)
        self.assertIsNone(store.tasks(rid)[0]['title'])

    @contextmanager
    def routed_browser(self,handler):
        # Wrap only the worker's Playwright entrypoint. No third-party site is contacted.
        with real_playwright() as pw:
            launch=pw.chromium.launch
            def wrapped_launch(*args,**kwargs):
                self.assertTrue(kwargs.get('headless'),'Normal batch must not open a visible browser')
                browser=launch(*args,**kwargs)
                new_context=browser.new_context
                def wrapped_context(*args,**kwargs):
                    context=new_context(*args,**kwargs)
                    context.route('**/*',handler)
                    return context
                patcher=patch.object(browser,'new_context',side_effect=wrapped_context)
                patcher.start();self.addCleanup(patcher.stop)
                return browser
            with patch.object(pw.chromium,'launch',side_effect=wrapped_launch):yield pw

    def fixture_handler(self,route):
        url=route.request.url
        path=url.split('fixture.test')[-1]
        self.paths.append(path)
        if path.startswith('/start'):
            target='/form' if 'fixture_auth=yes' in route.request.headers.get('cookie','') else '/login'
            body=f'<h1>Engineer posting</h1><button onclick="location.href=\'{target}\'">Apply now</button>'
        elif path=='/login':
            if getattr(self,'reject_login',False):
                action="document.getElementById('error').textContent='Email or password invalid'"
            elif self.missing_account:
                action="document.getElementById('error').textContent='No account found'"
            else:
                action="document.cookie='fixture_auth=yes; path=/';location.href='/form'"
            body=f'''<h1>Sign in</h1><label>Email<input type="email" required></label>
                <label>Password<input type="password" required></label><p id="error"></p>
                <button onclick="{action}">Sign in</button><a href="/register">Create account</a>'''
        elif path=='/register':
            body='''<h1>Create account</h1><label>Email<input type="email" required></label>
                <label>Password<input type="password" required></label><label>Confirm password<input type="password" required></label>
                <button onclick="location.href='/verify'">Create account</button>'''
        elif path=='/verify':
            body='''<h1>Enter verification code</h1><label>One-time code<input required></label>
                <button onclick="document.cookie='fixture_auth=yes; path=/';location.href='/form'">Verify</button>'''
        elif path=='/form':
            body='''<h1>Applicant details</h1><form><label>First Name<input required></label><label>Email<input type="email" required></label>
                <label>Clearance<select required><option value="">Select</option><option value="none">None</option><option>Secret</option></select></label>
                <button type="button" onclick="if(this.form.reportValidity()) location.href='/review'">Next</button></form>'''
        elif path=='/review':body='<h1>Review application</h1><button onclick="location.href=\'/done\'">Submit application</button>'
        elif path=='/done':body='<h1>Thank you for applying</h1><p>Application submitted.</p>'
        else:
            route.fulfill(status=404,body='Unexpected fixture URL');return
        route.fulfill(status=200,content_type='text/html',body=body)

    def operator(self,task_id,state,message,snapshot=None,screenshot=None):
        self.original_update(task_id,state,message,snapshot,screenshot)
        if not snapshot or state not in store.NEEDS_HELP:return
        self.events.append(state)
        self.assertNotIn('test-only-passphrase',json.dumps(snapshot))
        fields=snapshot['fields'];actions=snapshot['actions'];url=snapshot['url']
        def send(action,**kwargs):store.send_command(task_id,action,snapshot['view_id'],**kwargs)
        def click(label):
            match=next(action for action in actions if action['label']==label)
            send('act',action_id=match['id'])
        entered=message.startswith('Your entries')
        if state=='needs_credentials':
            vault.allow_shared(url);send('retry_login')
        elif state=='account_required':
            if url.endswith('/login'):click('Create account')
            elif entered:click('Create account')
            else:send('fields',changes={field['id']:'test-only-passphrase' if field['type']=='password' else 'candidate@example.test' for field in fields})
        elif state=='verification_required':
            if entered:click('Verify')
            else:send('fields',changes={fields[0]['id']:'123456'})
        elif state=='needs_information':
            if entered:send('resume')
            else:
                clearance=next(field for field in fields if field['label']=='Clearance')
                self.assertFalse(clearance['populated'],'Clearance must never be inferred by automatic filling')
                send('fields',changes={clearance['id']:1})
        elif state=='review_ready':
            self.assertNotEqual(db.get_job(store.get_task(task_id)['job_id'])['status'],'Applied')
            click('Submit application')

    def drive(self,missing_account=False,jobs=1):
        self.paths=[];self.events=[];self.missing_account=missing_account
        vault.save_credentials('candidate@example.test','test-only-passphrase')
        ids=[self.add_job(f'https://fixture.test/start{index}') for index in range(jobs)]
        rid=store.create_run(ids)
        self.original_update=store.update_task
        with patch('playwright.sync_api.sync_playwright',side_effect=lambda:self.routed_browser(self.fixture_handler)),patch.object(store,'update_task',side_effect=self.operator):
            run_batch(rid)
        self.assertEqual(store.get_run(rid)['state'],'finished')
        self.assertTrue(all(task['state']=='submitted' for task in store.tasks(rid)),store.tasks(rid))
        self.assertTrue(all(db.get_job(jid)['status']=='Applied' for jid in ids))
        return rid

    def test_sequential_login_fill_pause_review_submit_and_session_reuse(self):
        self.drive(jobs=2)
        self.assertEqual(self.paths.count('/login'),1,'Second job should reuse the encrypted login session')
        self.assertEqual(self.events.count('review_ready'),2)
        self.assertIn('needs_credentials',self.events)

    def test_two_step_login_handles_email_then_password(self):
        original=self.fixture_handler
        def handler(route):
            path=route.request.url.split('fixture.test')[-1]
            if path=='/login':
                route.fulfill(content_type='text/html',body='''<h1>Sign in</h1><label>Email<input type="email" required></label><button onclick="location.href='/password'">Continue</button>''')
            elif path=='/password':
                route.fulfill(content_type='text/html',body='''<h1>Sign in</h1><label>Password<input type="password" required></label><button onclick="document.cookie='fixture_auth=yes; path=/';location.href='/form'">Sign in</button>''')
            else:original(route)
        self.fixture_handler=handler
        self.drive()
        self.assertNotIn('login_failed',self.events)

    def test_apply_button_on_review_waits_for_explicit_user_action(self):
        original_handler=self.fixture_handler
        original_operator=self.operator
        def handler(route):
            if route.request.url.endswith('/review'):
                route.fulfill(content_type='text/html',body='''<h1>Review your application</h1><button onclick="location.href='/done'">Apply now</button>''')
            else:original_handler(route)
        def operator(task_id,state,message,snapshot=None,screenshot=None):
            if state=='review_ready' and snapshot and snapshot['url'].endswith('/review'):
                self.original_update(task_id,state,message,snapshot,screenshot)
                self.events.append(state)
                self.assertNotEqual(db.get_job(store.get_task(task_id)['job_id'])['status'],'Applied')
                action=next(a for a in snapshot['actions'] if a['label']=='Apply now')
                store.send_command(task_id,'act',snapshot['view_id'],action_id=action['id'])
            else:original_operator(task_id,state,message,snapshot,screenshot)
        self.fixture_handler=handler;self.operator=operator
        self.drive()
        self.assertIn('review_ready',self.events)

    def test_delayed_apply_and_starred_fields_continue_without_help(self):
        original=self.fixture_handler
        def handler(route):
            path=route.request.url.split('fixture.test')[-1]
            if path.startswith('/start'):
                route.fulfill(content_type='text/html',body='''<h1>Engineer</h1><div id="ready"></div><script>setTimeout(()=>{const btn=document.createElement('button');btn.textContent='Apply now';btn.onclick=()=>location.href='/routine';document.querySelector('#ready').append(btn)},1800)</script>''')
            elif path=='/routine':
                route.fulfill(content_type='text/html',body='''<h1>Applicant details</h1><label>First Name*<input required></label><button onclick="location.href='/review'">Save &amp; Continue</button>''')
            else:original(route)
        self.fixture_handler=handler
        self.drive()
        self.assertNotIn('needs_information',self.events)

    def test_missing_account_registration_and_verification_stay_in_app(self):
        self.drive(missing_account=True)
        self.assertIn('account_required',self.events)
        self.assertIn('verification_required',self.events)
        self.assertIn('/register',self.paths)

    def test_stop_prevents_opening_queued_jobs(self):
        rid=store.create_run([self.add_job()]);store.set_run_state(rid,'stopping')
        with patch('workflow_worker.run_task') as worker:run_batch(rid)
        worker.assert_not_called()
        self.assertEqual(store.tasks(rid)[0]['state'],'stopped')

    def test_failed_login_only_attempts_once_then_waits_for_operator(self):
        self.paths=[];self.missing_account=False;self.reject_login=True
        vault.save_credentials('candidate@example.test','test-only-passphrase','https://fixture.test/')
        jid=self.add_job();rid=store.create_run([jid])
        original=store.update_task
        failures=[]
        def operator(task_id,state,message,snapshot=None,screenshot=None):
            original(task_id,state,message,snapshot,screenshot)
            if state=='login_failed':
                failures.append(state)
                store.send_command(task_id,'skip',snapshot['view_id'])
        with patch('playwright.sync_api.sync_playwright',side_effect=lambda:self.routed_browser(self.fixture_handler)),patch.object(store,'update_task',side_effect=operator):
            run_batch(rid)
        self.assertEqual(failures,['login_failed'])
        self.assertEqual(store.tasks(rid)[0]['state'],'skipped')
        self.assertEqual(db.get_job(jid)['status'],'Needs review')

    def test_dashboard_credentials_and_assistance_controls(self):
        from streamlit.testing.v1 import AppTest
        jid=self.add_job();rid=store.create_run([jid]);task=store.tasks(rid)[0]
        app=AppTest.from_file('app.py',default_timeout=20).run()
        app.sidebar.radio[0].set_value('Accounts & Sessions').run()
        app.text_input(key='accounts_shared_email').set_value('candidate@example.test')
        app.text_input(key='accounts_shared_password').set_value('test-only-passphrase')
        next(button for button in app.button if button.label=='Save shared application login').click().run()
        self.assertFalse(app.exception)
        self.assertTrue(vault.credential_status())
        view={'view_id':'ui-test','url':'https://fixture.test/login','portal':'Generic form','fields':[],
              'actions':[{'id':'register','label':'Create account','frame':0,'role':'button'}]}
        store.update_task(task['id'],'account_required','Create your account to continue',snapshot=view)
        app.sidebar.radio[0].set_value('Batch Launch').run()
        self.assertFalse(app.exception)
        self.assertTrue(any('need your attention' in warning.value for warning in app.warning))
        self.assertTrue(any(button.label=='Retry with saved credentials' for button in app.button))
        self.assertTrue(any(button.label=='Skip this job and continue batch' for button in app.button))
        next(button for button in app.button if button.label=='Skip this job and continue batch').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(store.pop_command(task['id'])['action'],'skip')
        with patch('batch_control.batch_processes', return_value=[]):
            next(button for button in app.button if button.label=='Force stop all batches').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(store.get_run(rid)['state'], 'stopped')
        self.assertEqual(store.get_task(task['id'])['state'], 'stopped')
        with self.assertRaises(ValueError):store.send_command(task['id'],'resume')

    def test_browser_mirror_rejects_stale_page_and_supports_manual_checkbox(self):
        with real_playwright() as pw:
            browser=pw.chromium.launch()
            try:
                page=browser.new_page()
                page.set_content('<label>Consent<input type="checkbox" required></label><button>Continue</button>')
                view=capture(page)
                apply_changes(page,view,{view['fields'][0]['id']:True},self.root)
                self.assertTrue(page.get_by_label('Consent').is_checked())
                page.set_content('<h1>Different employer step</h1>')
                with self.assertRaises(ValueError):click_action(page,view,view['actions'][0]['id'])
            finally:browser.close()

    def test_safe_dropdown_defaults_and_cross_origin_credentials(self):
        from autofill import FIELDS
        with real_playwright() as pw:
            browser=pw.chromium.launch()
            try:
                page=browser.new_page()
                page.set_content('''<label>Country<select required><option value="choose">Select one</option><option>Exampleland</option></select></label>
                    <label>Citizenship<select required><option value="">Select</option><option>Exampleland</option></select></label>''')
                view=capture(page)
                self.assertTrue(fill_known_selects(page,view,{'country':'Exampleland'},dict(FIELDS,country=['Country','Citizenship'])))
                self.assertEqual(page.locator('select').nth(0).input_value(),'Exampleland')
                self.assertEqual(page.locator('select').nth(1).input_value(),'')
                context=browser.new_context()
                def serve(route):
                    if route.request.url.startswith('https://auth.test'):
                        body='<h1>Sign in</h1><label>Email<input type="email"></label><label>Password<input type="password"></label><button>Sign in</button>'
                    else:body='<iframe src="https://auth.test/login"></iframe>'
                    route.fulfill(status=200,content_type='text/html',body=body)
                context.route('**/*',serve)
                page=context.new_page();page.goto('https://fixture.test/login')
                page.frames[1].wait_for_selector('input')
                view=capture(page)
                self.assertFalse(autofill_login(page,view,{'email':'candidate@example.test','password':'test-only-passphrase'}))
                self.assertEqual(page.frames[1].get_by_label('Password').input_value(),'')
                context.close()
            finally:browser.close()


if __name__=='__main__':unittest.main()
