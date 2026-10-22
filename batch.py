"""Sequential background application queue with an in-app assistance inbox."""
import argparse
import sys
from workflow_store import create_run
from workflow_worker import run_batch

def main():
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--run-id')
    source.add_argument('--job-ids', help='Comma-separated saved job IDs')
    parser.add_argument('--workers', type=int, default=1, choices=[1], help='One application at a time')
    parser.add_argument('--resume', default='')
    args = parser.parse_args()
    run_id = args.run_id or create_run([int(value.strip()) for value in args.job_ids.split(',') if value.strip()], args.resume)
    run_batch(run_id)

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    main()
