#!/usr/bin/env python3
"""Local monitoring bootstrap and reports; never calls a model or sends a message."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import ai_monitoring as monitor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--month', default='2026-09')
    parser.add_argument('--bootstrap', action='store_true')
    parser.add_argument('--output')
    parser.add_argument('--replay-pending', action='store_true')
    parser.add_argument('--legacy-start', default='0001-01-01T00:00:00+00:00')
    args = parser.parse_args()
    if not monitor.enabled():
        raise SystemExit('AI_MONITORING_ENABLED must be explicitly enabled')
    if args.replay_pending:
        monitor.replay_pending()
    if args.bootstrap:
        monitor.seed_forms()
        monitor.import_legacy(Path(__file__).resolve().parents[1] / 'logs' / 'agent.log', args.legacy_start)
    result = monitor.report(args.month)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix+'.tmp')
        temporary.write_text(json.dumps(result, indent=2))
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
