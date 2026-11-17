"""Administration CLI (run on the server, uses the same database).

  python -m backend.admin create-enroll-code "Lab PCs" --uses 40 --days 60
  python -m backend.admin create-client "Teacher PC" --select-model
  python -m backend.admin list-clients
  python -m backend.admin disable-client c_123abc
  python -m backend.admin enable-client  c_123abc
  python -m backend.admin set-limits c_123abc --minute 10 --day 300 --month 5000
  python -m backend.admin usage [--days 30]
  python -m backend.admin set-chain "gemini:gemini-3.5-flash,groq:llama-3.3-70b-versatile"
  python -m backend.admin models gemini
"""
from __future__ import annotations

import argparse
import json
import time

from .authentication import Authenticator
from .db import Database
from .providers import PROVIDER_CLASSES, Router, parse_chain
from .settings import load_settings
from .usage_tracking import UsageTracker


def main(argv=None) -> int:
    s = load_settings()
    p = argparse.ArgumentParser(prog="backend.admin")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("create-enroll-code"); a.add_argument("label")
    a.add_argument("--uses", type=int, default=30); a.add_argument("--days", type=int, default=30)
    a = sub.add_parser("create-client"); a.add_argument("name"); a.add_argument("--select-model", action="store_true")
    sub.add_parser("list-clients")
    sub.add_parser("list-codes")
    a = sub.add_parser("disable-client"); a.add_argument("id")
    a = sub.add_parser("enable-client"); a.add_argument("id")
    a = sub.add_parser("set-limits"); a.add_argument("id")
    a.add_argument("--minute", type=int); a.add_argument("--day", type=int); a.add_argument("--month", type=int)
    a = sub.add_parser("usage"); a.add_argument("--days", type=int, default=30)
    a = sub.add_parser("set-chain"); a.add_argument("chain")
    a = sub.add_parser("models"); a.add_argument("provider", choices=sorted(PROVIDER_CLASSES))
    args = p.parse_args(argv)

    db = Database(s.db_path)
    auth = Authenticator(db, s.admin_token)
    if args.cmd == "create-enroll-code":
        code = auth.create_enroll_code(args.label, args.uses, args.days)
        print(f"Enrollment code (shown once): {code}\n  uses={args.uses} valid_days={args.days}")
    elif args.cmd == "create-client":
        cid, token = auth.create_client(args.name, can_select_model=args.select_model)
        print(f"client_id={cid}\ntoken (shown once, give it to that one computer): {token}")
    elif args.cmd == "list-clients":
        for r in db.all("SELECT * FROM clients ORDER BY created_at"):
            seen = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["last_seen"])) if r["last_seen"] else "-"
            print(f"{r['id']}  {r['name']:<24} disabled={r['disabled']} select_model={r['can_select_model']} "
                  f"limits={r['per_minute']}/{r['per_day']}/{r['per_month']} last_seen={seen} via={r['enrolled_with']}")
    elif args.cmd == "list-codes":
        for r in db.all("SELECT * FROM enroll_codes ORDER BY created_at"):
            exp = time.strftime("%Y-%m-%d", time.localtime(r["expires_at"])) if r["expires_at"] else "never"
            print(f"{r['label']:<24} uses={r['uses']}/{r['max_uses']} expires={exp} disabled={r['disabled']}")
    elif args.cmd in ("disable-client", "enable-client"):
        db.execute("UPDATE clients SET disabled=? WHERE id=?", (int(args.cmd == "disable-client"), args.id))
        print("ok")
    elif args.cmd == "set-limits":
        db.execute("UPDATE clients SET per_minute=COALESCE(?,per_minute), per_day=COALESCE(?,per_day), "
                   "per_month=COALESCE(?,per_month) WHERE id=?", (args.minute, args.day, args.month, args.id))
        print("ok")
    elif args.cmd == "usage":
        print(json.dumps(UsageTracker(db).summary(args.days), indent=2))
    elif args.cmd == "set-chain":
        if not parse_chain(args.chain):
            print("invalid chain"); return 1
        db.set_setting("chain", args.chain)
        print("chain saved (running servers pick it up after restart, or use POST /v1/admin/chain)")
    elif args.cmd == "models":
        print("\n".join(Router(s.keys, s.chain).provider(args.provider).list_models()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
