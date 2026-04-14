#!/usr/bin/env python3
"""Enqueue a commit for off-hours production deploy. Called by CI workflow.
Subject is base64-encoded by the caller to survive shell quoting issues
with quotes / backticks / dollar signs in commit messages."""
import argparse
import base64
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from shared import deploy_queue


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sha", required=True)
    p.add_argument("--short-sha", required=True)
    p.add_argument("--subject-b64", required=True,
                   help="Base64-encoded commit subject (UTF-8)")
    args = p.parse_args()
    subject = base64.b64decode(args.subject_b64).decode("utf-8")
    state = deploy_queue.enqueue(args.sha, args.short_sha, subject)
    print(f"Enqueued. Queue length: {len(state['queued'])}")


if __name__ == "__main__":
    main()
