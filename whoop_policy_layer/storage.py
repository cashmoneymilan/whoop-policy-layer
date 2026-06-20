"""Tiny persistence layer for tokens and policy audit logs."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

from whoop_policy_layer.config import DATABASE_URL


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Storage:
    """Small SQL storage wrapper.

    SQLite is the local default; Railway Postgres works when DATABASE_URL starts
    with postgres:// or postgresql://.
    """

    def __init__(self, database_url: str = DATABASE_URL) -> None:
        self.database_url = database_url
        parsed = urlparse(database_url)
        self.backend = "postgres" if parsed.scheme in {"postgres", "postgresql"} else "sqlite"
        if self.backend == "sqlite" and parsed.scheme == "sqlite":
            path = parsed.path
            if parsed.netloc:
                path = f"//{parsed.netloc}{parsed.path}"
            self.path = Path(path).expanduser().resolve()
            self.path.parent.mkdir(parents=True, exist_ok=True)
        elif self.backend == "sqlite":
            path = database_url
            self.path = Path(path).expanduser().resolve()
            self.path.parent.mkdir(parents=True, exist_ok=True)
        else:
            self.path = None
        self.init()

    @contextmanager
    def connect(self) -> Iterator[Any]:
        if self.backend == "postgres":
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as error:
                raise RuntimeError("Postgres DATABASE_URL requires psycopg[binary].") from error
            conn = psycopg.connect(self.database_url, row_factory=dict_row)
        else:
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def sql(self, query: str) -> str:
        return query.replace("?", "%s") if self.backend == "postgres" else query

    def init(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS oauth_tokens (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    access_token TEXT NOT NULL,
                    refresh_token TEXT,
                    expires_at TEXT,
                    scope TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS policy_decisions (
                    decision_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    trigger_source TEXT,
                    input_json TEXT NOT NULL,
                    policy_json TEXT NOT NULL,
                    approved_message_json TEXT NOT NULL,
                    audit_json TEXT NOT NULL,
                    message_sent INTEGER,
                    checkin_id TEXT,
                    outcome_note TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def save_token(self, token: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                self.sql(
                    """
                INSERT INTO oauth_tokens (id, access_token, refresh_token, expires_at, scope, updated_at)
                VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    access_token=excluded.access_token,
                    refresh_token=COALESCE(excluded.refresh_token, oauth_tokens.refresh_token),
                    expires_at=excluded.expires_at,
                    scope=excluded.scope,
                    updated_at=excluded.updated_at
                """
                ),
                (
                    token["access_token"],
                    token.get("refresh_token"),
                    token.get("expires_at"),
                    token.get("scope"),
                    now_iso(),
                ),
            )

    def get_token(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM oauth_tokens WHERE id = 1").fetchone()
        return dict(row) if row else None

    def log_decision(self, contract: dict[str, Any], trigger_source: str = "") -> dict[str, Any]:
        timestamp = now_iso()
        decision_id = contract["decision_id"]
        audit = dict(contract.get("audit") or {})
        audit.update({"logged": True, "verification_status": "Verified Log"})
        with self.connect() as conn:
            conn.execute(
                self.sql(
                    """
                INSERT INTO policy_decisions (
                    decision_id, state, trigger_source, input_json, policy_json,
                    approved_message_json, audit_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(decision_id) DO UPDATE SET
                    state=excluded.state,
                    trigger_source=excluded.trigger_source,
                    input_json=excluded.input_json,
                    policy_json=excluded.policy_json,
                    approved_message_json=excluded.approved_message_json,
                    audit_json=excluded.audit_json,
                    updated_at=excluded.updated_at
                """
                ),
                (
                    decision_id,
                    contract["state"],
                    trigger_source,
                    json.dumps(contract.get("inputs") or {}, sort_keys=True),
                    json.dumps(contract.get("policy") or {}, sort_keys=True),
                    json.dumps(contract.get("approved_message") or {}, sort_keys=True),
                    json.dumps(audit, sort_keys=True),
                    timestamp,
                    timestamp,
                ),
            )
        contract["audit"] = audit
        return contract

    def record_outcome(self, decision_id: str, sent: bool, checkin_id: str = "", outcome_note: str = "") -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(self.sql("SELECT decision_id FROM policy_decisions WHERE decision_id = ?"), (decision_id,)).fetchone()
            if not row:
                timestamp = now_iso()
                conn.execute(
                    self.sql(
                        """
                    INSERT INTO policy_decisions (
                        decision_id, state, trigger_source, input_json, policy_json,
                        approved_message_json, audit_json, message_sent, checkin_id,
                        outcome_note, created_at, updated_at
                    )
                    VALUES (?, 'unknown', 'manual_outcome', '{}', '{}', '{}', ?, ?, ?, ?, ?, ?)
                    """
                    ),
                    (
                        decision_id,
                        json.dumps({"logged": True, "verification_status": "Outcome Without Prior Decision"}),
                        1 if sent else 0,
                        checkin_id,
                        outcome_note,
                        timestamp,
                        timestamp,
                    ),
                )
                return {"status": "created_without_prior_decision", "decision_id": decision_id}
            conn.execute(
                self.sql(
                    """
                UPDATE policy_decisions
                SET message_sent = ?, checkin_id = ?, outcome_note = ?, updated_at = ?
                WHERE decision_id = ?
                """
                ),
                (1 if sent else 0, checkin_id, outcome_note, now_iso(), decision_id),
            )
        return {"status": "updated", "decision_id": decision_id, "sent": sent}
