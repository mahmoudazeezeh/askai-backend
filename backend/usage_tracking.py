"""Usage tracking (requests, tokens, latency, errors) in SQLite."""
from __future__ import annotations

import time

from .db import Database


def _day(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts or time.time()))


def _month(ts: float | None = None) -> str:
    return time.strftime("%Y-%m", time.gmtime(ts or time.time()))


# statuses that count against a client's quota (errors caused by the
# provider / service are not charged to the student)
CHARGED = ("ok", "truncated")


class UsageTracker:
    def __init__(self, db: Database):
        self.db = db

    def record(self, client_id: str, *, mode: str, provider: str = "", model: str = "",
               status: str, in_tokens: int = 0, out_tokens: int = 0, ms: int = 0,
               error: str = "") -> None:
        now = time.time()
        self.db.execute(
            "INSERT INTO usage(client_id,ts,day,month,mode,provider,model,status,in_tokens,out_tokens,ms,error)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (client_id, int(now), _day(now), _month(now), mode, provider, model, status,
             in_tokens, out_tokens, ms, error[:300]),
        )

    def _count(self, where: str, params: tuple) -> int:
        q = f"SELECT COUNT(*) AS n FROM usage WHERE {where} AND status IN ({','.join('?' * len(CHARGED))})"
        return int(self.db.one(q, params + CHARGED)["n"])

    def count_today(self, client_id: str) -> int:
        return self._count("client_id=? AND day=?", (client_id, _day()))

    def count_month(self, client_id: str) -> int:
        return self._count("client_id=? AND month=?", (client_id, _month()))

    def count_today_global(self) -> int:
        return self._count("day=?", (_day(),))

    def summary(self, days: int = 30) -> list[dict]:
        since = int(time.time()) - days * 86400
        rows = self.db.all(
            "SELECT u.client_id, c.name, COUNT(*) AS requests, "
            "SUM(CASE WHEN u.status IN ('ok','truncated') THEN 1 ELSE 0 END) AS ok, "
            "SUM(u.in_tokens) AS in_tok, SUM(u.out_tokens) AS out_tok "
            "FROM usage u LEFT JOIN clients c ON c.id=u.client_id WHERE u.ts>=? "
            "GROUP BY u.client_id ORDER BY requests DESC", (since,))
        return [dict(r) for r in rows]
