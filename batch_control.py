"""Emergency termination scoped to this project's batch process trees."""
from pathlib import Path

import psutil

import db
import workflow_store as store


def batch_processes(root=None):
    script = (Path(root) if root else db.ROOT) / 'batch.py'
    result = []
    for process in psutil.process_iter():
        try:
            args = process.cmdline()
            if not process.name().lower().startswith('python') or len(args) < 2:
                continue
            candidate = Path(args[1])
            if not candidate.is_absolute():
                candidate = Path(process.cwd()) / candidate
            if candidate.resolve() == script.resolve():
                result.append(process)
        except (psutil.Error, OSError):
            continue
    return result


def kill_batch_tree(process):
    """Freeze the scheduler before collecting children; retain process identities."""
    frozen = []
    try:
        process.suspend()
        frozen.append(process)
        children = process.children(recursive=True)
        for child in children:
            try:
                child.suspend()
                frozen.append(child)
            except psutil.NoSuchProcess:
                pass
        # Collect again after child schedulers have been frozen.
        targets = list({p.pid: p for p in [process, *children, *process.children(recursive=True)]}.values())
        for target in targets:
            try:
                target.kill()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(targets, timeout=5)
        if alive:
            raise RuntimeError('Some batch processes are still running. Try Force stop again.')
    except psutil.NoSuchProcess:
        pass
    finally:
        for target in frozen:
            try:
                if target.is_running():
                    target.resume()
            except psutil.Error:
                pass


def force_stop_batches():
    active = [run for run in store.runs() if run['state'] in ('running', 'stopping')]
    for run in active:
        store.set_run_state(run['id'], 'stopping')
    processes = batch_processes()
    for process in processes:
        kill_batch_tree(process)
    for run in active:
        store.finish_run(run['id'], 'stopped')
    return len(processes)
