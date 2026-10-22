"""Force-stop checks use harmless local Python sleepers, never employer sites."""
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import psutil

import batch_control as control


class BatchControlTests(unittest.TestCase):
    def test_only_project_batch_and_children_are_killed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            child_file = root / 'child.txt'
            script = root / 'batch.py'
            script.write_text("import subprocess,sys,time\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'])\nPath(sys.argv[1]).write_text(str(p.pid))\ntime.sleep(120)\n")
            unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
            worker = subprocess.Popen([sys.executable, str(script), str(child_file)])
            child = None
            try:
                deadline = time.monotonic() + 15
                while not child_file.exists() and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertTrue(child_file.exists())
                child = psutil.Process(int(child_file.read_text()))
                found = control.batch_processes(root)
                self.assertTrue(found)
                self.assertFalse(control.batch_processes(root / 'other-project'))
                for process in found:
                    control.kill_batch_tree(process)
                worker.wait(timeout=10)
                self.assertFalse(child.is_running())
                self.assertIsNone(unrelated.poll())
            finally:
                for process in (worker, unrelated):
                    if process.poll() is None: process.kill()
                    process.wait(timeout=10)
                if child and child.is_running(): child.kill()

    def test_stop_closes_active_records_after_termination(self):
        with patch.object(control.store, 'runs', return_value=[{'id':'active','state':'running'}, {'id':'old','state':'finished'}]), patch.object(control.store, 'set_run_state') as stopping, patch.object(control.store, 'finish_run') as finish, patch.object(control, 'batch_processes', return_value=['worker']), patch.object(control, 'kill_batch_tree') as kill:
            control.force_stop_batches()
            stopping.assert_called_once_with('active', 'stopping')
            kill.assert_called_once_with('worker')
            finish.assert_called_once_with('active', 'stopped')

    def test_failure_does_not_claim_batch_has_stopped(self):
        with patch.object(control.store, 'runs', return_value=[{'id':'active','state':'running'}]), patch.object(control.store, 'set_run_state'), patch.object(control.store, 'finish_run') as finish, patch.object(control, 'batch_processes', return_value=['worker']), patch.object(control, 'kill_batch_tree', side_effect=psutil.AccessDenied(123)):
            with self.assertRaises(psutil.AccessDenied): control.force_stop_batches()
            finish.assert_not_called()
