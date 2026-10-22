"""Launch multiple independent, visible autofill workers with a concurrency cap."""
import argparse, concurrent.futures, subprocess, sys
from pathlib import Path
from db import ROOT, DATA, get_job

def run_one(job_id, resume):
    log_dir = DATA / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    args = [sys.executable, str(ROOT / 'autofill.py'), '--job-id', str(job_id), '--wait-for-session']
    if resume:
        args += ['--resume', resume]
    with (log_dir / f'job-{job_id}.log').open('a', encoding='utf-8') as log:
        log.write(f'Launching {job_id}\n')
        log.flush()
        return subprocess.run(args, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT).returncode

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job-ids', required=True, help='Comma-separated saved job IDs')
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--resume', default='')
    args = parser.parse_args()
    job_ids = list(dict.fromkeys(int(x.strip()) for x in args.job_ids.split(',') if x.strip()))
    if not 1 <= args.workers <= 5:
        parser.error('workers must be between 1 and 5')
    invalid = [jid for jid in job_ids if not get_job(jid)]
    if invalid:
        parser.error(f'Unknown job IDs: {invalid}')
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_one, jid, args.resume): jid for jid in job_ids}
        for future in concurrent.futures.as_completed(futures):
            print(f'Job {futures[future]} finished with exit code {future.result()}', flush=True)

if __name__ == '__main__':
    main()
