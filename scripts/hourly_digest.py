"""Run the hourly digest once, or loop on a cron expression. Dry-run unless DIGEST_LIVE=1.

  python3.12 scripts/hourly_digest.py            # once, dry-run, writes outbox/*.eml
  python3.12 scripts/hourly_digest.py --loop     # loop on '0 * * * *'
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retail_agents.restaurant_demo import run  # noqa: E402
from retail_agents.scheduler import run_loop  # noqa: E402


def job(_now=None):
    if os.environ.get("DIGEST_LIVE") == "1":
        sys.exit("Live sending is not wired into the synthetic demo. Build a site runner with "
                 "EmailSender(dry_run=False, config=SmtpConfig.from_env()).")
    r = run(outbox=os.environ.get("DIGEST_OUTBOX", "outbox"))
    print(f"{r['digest'].subject} -> {r['eml']} (dry-run, not sent)")


if __name__ == "__main__":
    if "--loop" in sys.argv:
        run_loop(os.environ.get("DIGEST_CRON", "0 * * * *"), job)
    else:
        job()
