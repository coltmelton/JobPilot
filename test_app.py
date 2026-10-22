"""Offline checks using temporary storage; never modify the applicant's data."""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import db
from applicant import history_rows
from streamlit.testing.v1 import AppTest


class ApplicantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.patcher = patch.multiple(db, DATA=root, DB=root / 'jobs.sqlite3')
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_existing_database_migrates_without_losing_jobs(self):
        with closing(sqlite3.connect(db.DB)) as connection:
            connection.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, company TEXT, title TEXT, url TEXT, location TEXT, status TEXT, notes TEXT, answers TEXT, created_at TEXT)")
            connection.execute("INSERT INTO jobs VALUES (1, 'RTX', 'Engineer', 'https://example.com', '', 'Saved', '', '{}', '')")
            connection.commit()
        db.update_job(1, application_details=json.dumps({'requisition_id': 'R123'}))
        job = db.get_job(1)
        self.assertEqual(job['title'], 'Engineer')
        self.assertEqual(json.loads(job['application_details'])['requisition_id'], 'R123')
        self.assertEqual(len(db.get_jobs()), 1)

    def test_profile_editor_saves_and_preserves_existing_fields(self):
        db.save_profile({'first_name': 'Zoë', 'custom_existing': 'keep'})
        app = AppTest.from_file('app.py', default_timeout=15).run()
        app.sidebar.radio[0].set_value('My Profile').run()
        self.assertFalse(app.exception)
        next(field for field in app.text_input if field.label == 'Middle name').set_value('Anne')
        next(field for field in app.selectbox if field.label == 'Require employment sponsorship now').select('No')
        next(button for button in app.button if button.label == 'Save profile').click().run()
        self.assertFalse(app.exception)
        saved = db.profile()
        self.assertEqual(saved['first_name'], 'Zoë')
        self.assertEqual(saved['middle_name'], 'Anne')
        self.assertEqual(saved['sponsorship_now'], 'No')
        self.assertEqual(saved['custom_existing'], 'keep')

    def test_application_requirements_save(self):
        db.save_job('RTX', 'Engineer', 'https://example.com')
        app = AppTest.from_file('app.py', default_timeout=15).run()
        app.sidebar.radio[0].set_value('Review & Launch').run()
        self.assertFalse(app.exception)
        next(field for field in app.text_input if field.label == 'Requisition / job ID').set_value('R123')
        app.checkbox[0].check()
        next(button for button in app.button if button.label == 'Save application preparation').click().run()
        self.assertFalse(app.exception)
        details = json.loads(db.get_jobs()[0]['application_details'])
        self.assertEqual(details['requisition_id'], 'R123')
        self.assertTrue(next(iter(details['checklist'].values())))

    def test_history_ignores_empty_rows(self):
        self.assertEqual(history_rows([{'School': ''}, {'School': ' Example '}], ['School']), [{'School': 'Example'}])

    def test_queue_reset_archives_jobs_and_keeps_profile(self):
        db.save_profile({'clearance_level': 'None', 'matching': {'years_experience': 3}})
        jid = db.save_job('RTX', 'Engineer', 'https://example.com/job/1')
        db.update_job(jid, notes='Keep in backup', answers='{"Question": "Answer"}')
        count, backup = db.clear_job_queue()
        self.assertEqual(count, 1)
        archived = json.loads(backup.read_text(encoding='utf-8'))['jobs']
        self.assertEqual(archived[0]['notes'], 'Keep in backup')
        self.assertEqual(archived[0]['answers'], '{"Question": "Answer"}')
        self.assertEqual(db.get_jobs(), [])
        self.assertEqual(db.profile()['clearance_level'], 'None')
        self.assertEqual(db.clear_job_queue(), (0, None))

    def test_queue_reset_does_not_delete_if_backup_fails(self):
        db.save_job('RTX', 'Engineer', 'https://example.com/job/1')
        with patch.object(Path, 'write_text', side_effect=OSError('Backup failed')):
            with self.assertRaises(OSError):db.clear_job_queue()
        self.assertEqual(len(db.get_jobs()), 1)


if __name__ == '__main__':
    unittest.main()
