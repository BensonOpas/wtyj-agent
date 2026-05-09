#!/usr/bin/env python3
"""CLI for unboks Tasks API. Operator-side dev tool.

Auth: prompts for unboks dashboard password on first use, caches the
session token at ~/.claude/projects/-Users-benson-Projects-bluemarlin-agent/auth/unboks_token
(0600 perms). On 401, silently re-logs in.

Usage:
    tasks.py list [--status open|done|all]
    tasks.py find <substring>          # substring match on body
    tasks.py show <id_or_substring>    # full body
    tasks.py done <id_or_substring>    # mark status=done
    tasks.py open <id_or_substring>    # mark status=open

Substring matches require a UNIQUE result; ambiguous matches print all
candidates and exit non-zero.
"""
import argparse
import getpass
import json
import os
import sys
from pathlib import Path

import requests

API_BASE = "https://api.unboks.org/api/unboks"
TOKEN_PATH = (
    Path.home()
    / ".claude/projects/-Users-benson-Projects-bluemarlin-agent/auth/unboks_token"
)
PASSWORD_ENV = "UNBOKS_DASHBOARD_PASSWORD"
PASSWORD_FILE_ENV = "UNBOKS_DASHBOARD_PASSWORD_FILE"
DEFAULT_PASSWORD_FILE = (
    Path.home()
    / ".claude/projects/-Users-benson-Projects-bluemarlin-agent/auth/unboks_password"
)


def _read_password():
    p = os.environ.get(PASSWORD_ENV)
    if p:
        return p
    pf = os.environ.get(PASSWORD_FILE_ENV)
    if pf and Path(pf).exists():
        return Path(pf).read_text().strip()
    if DEFAULT_PASSWORD_FILE.exists():
        return DEFAULT_PASSWORD_FILE.read_text().strip()
    return getpass.getpass("unboks dashboard password: ")


def _login(password=None):
    if password is None:
        password = _read_password()
    r = requests.post(
        f"{API_BASE}/dashboard/api/login",
        json={"password": password},
        timeout=10,
    )
    r.raise_for_status()
    token = r.json()["token"]
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(token)
    TOKEN_PATH.chmod(0o600)
    return token


def _token(refresh=False):
    if refresh or not TOKEN_PATH.exists():
        return _login()
    return TOKEN_PATH.read_text().strip()


def _api(method, path, **kwargs):
    """Call API with auth, retry once on 401."""
    for attempt in (1, 2):
        token = _token(refresh=(attempt == 2))
        kwargs.setdefault("headers", {})["Authorization"] = f"Bearer {token}"
        r = requests.request(method, f"{API_BASE}{path}", timeout=15, **kwargs)
        if r.status_code == 401 and attempt == 1:
            continue
        r.raise_for_status()
        if r.status_code == 204 or not r.content:
            return None
        return r.json()
    raise RuntimeError("auth failed after retry")


def _short_body(t, n=80):
    body = (t.get("bodyText") or t.get("bodyHtml") or "").strip()
    body = body.replace("\n", " ").replace("\r", " ")
    return body[:n] + ("…" if len(body) > n else "")


def _resolve(query, tasks):
    """Find a unique task by exact id, hex prefix (>=8 chars), or substring on body.
    Returns task dict or exits with diagnostic."""
    matches = [t for t in tasks if t["id"] == query]
    if matches:
        return matches[0]
    if len(query) >= 8 and all(c in "0123456789abcdef" for c in query.lower()):
        prefix_matches = [t for t in tasks if t["id"].startswith(query.lower())]
        if len(prefix_matches) == 1:
            return prefix_matches[0]
        if len(prefix_matches) > 1:
            print(f"Ambiguous id prefix {query!r}:", file=sys.stderr)
            for t in prefix_matches:
                print(
                    f"  {t['id']} · {t['status']:6s} · {_short_body(t)}",
                    file=sys.stderr,
                )
            sys.exit(2)
    q_low = query.lower()
    matches = [
        t
        for t in tasks
        if q_low in (t.get("bodyText") or "").lower()
        or q_low in (t.get("bodyHtml") or "").lower()
    ]
    if not matches:
        print(f"No task matches: {query!r}", file=sys.stderr)
        sys.exit(2)
    if len(matches) > 1:
        print(
            f"Ambiguous: {len(matches)} tasks match {query!r}:", file=sys.stderr
        )
        for t in matches:
            print(
                f"  {t['id'][:12]} · {t['status']:6s} · {_short_body(t)}",
                file=sys.stderr,
            )
        sys.exit(2)
    return matches[0]


def cmd_list(args):
    tasks = _api("GET", "/tasks") or []
    if args.status != "all":
        tasks = [t for t in tasks if t.get("status") == args.status]
    if not tasks:
        print(f"(no tasks with status={args.status})")
        return
    tasks.sort(key=lambda t: t.get("createdAt") or "")
    for t in tasks:
        print(
            f"{t['id'][:12]} · {t.get('status'):6s} · "
            f"to:{t.get('assignedTo'):8s} · {_short_body(t)}"
        )


def cmd_find(args):
    tasks = _api("GET", "/tasks") or []
    q_low = args.query.lower()
    matches = [
        t
        for t in tasks
        if q_low in (t.get("bodyText") or "").lower()
        or q_low in (t.get("bodyHtml") or "").lower()
    ]
    if not matches:
        print(f"(no matches for {args.query!r})")
        return
    matches.sort(key=lambda t: t.get("createdAt") or "")
    for t in matches:
        print(
            f"{t['id'][:12]} · {t.get('status'):6s} · "
            f"to:{t.get('assignedTo'):8s} · {_short_body(t)}"
        )


def cmd_show(args):
    tasks = _api("GET", "/tasks") or []
    t = _resolve(args.task, tasks)
    print(f"id:           {t['id']}")
    print(f"status:       {t.get('status')}")
    print(f"assigned to:  {t.get('assignedTo')}")
    print(f"created by:   {t.get('createdBy')}")
    print(f"created at:   {t.get('createdAt')}")
    if t.get("completedAt"):
        print(f"completed at: {t['completedAt']} (by {t.get('completedBy')})")
    print()
    body = t.get("bodyText") or "(no description)"
    print(body)


def cmd_set_status(args, status):
    tasks = _api("GET", "/tasks") or []
    t = _resolve(args.task, tasks)
    payload = {"status": status}
    if status == "done":
        payload["completedBy"] = "Jr"
    updated = _api("PATCH", f"/tasks/{t['id']}", json=payload)
    print(f"{t['id'][:12]} → {updated.get('status')}: {_short_body(t, 60)}")


def cmd_create(args):
    body_text = args.body
    if args.body_file:
        body_text = Path(args.body_file).read_text()
    payload = {
        "assignedTo": args.to,
        "createdBy": args.from_,
        "bodyText": body_text,
    }
    created = _api("POST", "/tasks", json=payload)
    tid = created.get("id", "?")
    num = created.get("taskNumber") or created.get("task_number") or "?"
    print(f"created #{num} {tid[:12]} → to:{args.to} from:{args.from_}")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list tasks")
    p_list.add_argument(
        "--status",
        default="open",
        choices=["open", "done", "parked", "all"],
    )

    p_find = sub.add_parser("find", help="search by body substring")
    p_find.add_argument("query")

    p_show = sub.add_parser("show", help="show full task body")
    p_show.add_argument("task", help="task id or unique body substring")

    p_done = sub.add_parser("done", help="mark task done")
    p_done.add_argument("task", help="task id or unique body substring")

    p_open = sub.add_parser("open", help="reopen task")
    p_open.add_argument("task", help="task id or unique body substring")

    p_create = sub.add_parser("create", help="create a new task")
    p_create.add_argument("--to", required=True, help="assignedTo (e.g. SR, Jr, Calvin)")
    p_create.add_argument("--from", dest="from_", default="Jr", help="createdBy")
    p_create.add_argument("--body", default="", help="task body text inline")
    p_create.add_argument("--body-file", help="read body from file (overrides --body)")

    args = p.parse_args()
    if args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "find":
        cmd_find(args)
    elif args.cmd == "show":
        cmd_show(args)
    elif args.cmd == "done":
        cmd_set_status(args, "done")
    elif args.cmd == "open":
        cmd_set_status(args, "open")
    elif args.cmd == "create":
        cmd_create(args)


if __name__ == "__main__":
    main()
