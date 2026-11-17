"""Durable single synthetic-device lease; no real device or OS isolation.

SQLite serializes owners across managers/processes sharing this database. A
process restart never steals a lease. The supervisor supplies termination and
cleanup proof; these booleans are a boundary, not a claim of physical recovery.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3


DEVICE_ID = "synthetic-device-p4"
_SYNTHETIC_ID = re.compile(r"synthetic-[A-Za-z0-9][A-Za-z0-9_.-]{0,180}\Z")
_CLEANUP = {"completed", "failed", "unknown"}


class LeaseError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Token:
    device_id: str
    run_id: str
    boot_epoch: str
    generation: int
    attempt_id: str = ""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _identifier(value):
    if not isinstance(value, str) or not _SYNTHETIC_ID.fullmatch(value):
        raise LeaseError("INVALID_SYNTHETIC_IDENTIFIER")


def _token(row):
    return Token(**{key: row[key] for key in Token.__dataclass_fields__})


class LeaseStore:
    """A single device row with explicit safe release and fail-closed restart."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS device_lease (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                device_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                boot_epoch TEXT NOT NULL,
                generation INTEGER NOT NULL CHECK(generation >= 0),
                attempt_id TEXT NOT NULL,
                lifecycle TEXT NOT NULL CHECK(lifecycle IN
                    ('free','active','cleaning','recovery_required')),
                recovery_reason TEXT NOT NULL,
                acquired_at TEXT,
                updated_at TEXT NOT NULL
            )""")
            db.execute("""INSERT OR IGNORE INTO device_lease VALUES
                (1, ?, '', '', 0, '', 'free', '', NULL, ?)""", (DEVICE_ID, _now()))

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _row(db):
        return dict(db.execute("SELECT * FROM device_lease WHERE singleton=1").fetchone())

    @staticmethod
    def _match(row, token):
        if not isinstance(token, Token) or _token(row) != token:
            raise LeaseError("STALE_LEASE")

    @staticmethod
    def _proof(terminated, cleanup_status):
        if (type(terminated) is not bool or not isinstance(cleanup_status, str)
                or cleanup_status not in _CLEANUP):
            raise LeaseError("INVALID_CLEANUP_PROOF")

    def inspect(self):
        with self._transaction() as db:
            row = self._row(db)
            del row["singleton"]
            return row

    def acquire(self, run_id: str, boot_epoch: str):
        """Return a new token only from free; existing ownership is never stolen."""
        _identifier(run_id)
        if not isinstance(boot_epoch, str) or not 1 <= len(boot_epoch) <= 200:
            raise LeaseError("INVALID_BOOT_EPOCH")
        with self._transaction() as db:
            row = self._row(db)
            if row["lifecycle"] != "free":
                return None
            now = _now()
            db.execute("""UPDATE device_lease SET run_id=?, boot_epoch=?,
                generation=generation+1, attempt_id='', lifecycle='active',
                recovery_reason='', acquired_at=?, updated_at=? WHERE singleton=1""",
                (run_id, boot_epoch, now, now))
            return _token(self._row(db))

    def activate_attempt(self, token: Token, attempt_id: str):
        _identifier(attempt_id)
        with self._transaction() as db:
            row = self._row(db)
            self._match(row, token)
            if row["lifecycle"] != "active" or row["attempt_id"]:
                raise LeaseError("INVALID_LEASE_TRANSITION")
            db.execute("UPDATE device_lease SET attempt_id=?, updated_at=? WHERE singleton=1",
                       (attempt_id, _now()))
            return _token(self._row(db))

    def authorize(self, token: Token, operation: str, item_id=None):
        """Validate a call before execution; no shell or arbitrary operation exists.

        The supervisor maps selected item IDs to attempts. Optional item_id is
        an attempt-scope assertion here, not an independent catalog lookup.
        """
        if operation not in {"p2.capture", "p3.check"}:
            raise LeaseError("OPERATION_NOT_ALLOWED")
        with self._transaction() as db:
            row = self._row(db)
            self._match(row, token)
            if row["lifecycle"] != "active":
                raise LeaseError("LEASE_REVOKED")
            if operation == "p3.check" and not row["attempt_id"]:
                raise LeaseError("ATTEMPT_REQUIRED")
            if operation == "p2.capture" and row["attempt_id"]:
                raise LeaseError("ATTEMPT_SCOPE_MISMATCH")
            if item_id is not None and item_id != row["attempt_id"]:
                raise LeaseError("ATTEMPT_SCOPE_MISMATCH")
            return True

    def begin_cleanup(self, token: Token):
        """Revoke normal calls before cancelling or cleaning owned resources."""
        with self._transaction() as db:
            row = self._row(db)
            self._match(row, token)
            if row["lifecycle"] not in {"active", "cleaning"}:
                raise LeaseError("INVALID_LEASE_TRANSITION")
            db.execute("UPDATE device_lease SET lifecycle='cleaning', updated_at=? WHERE singleton=1",
                       (_now(),))

    def _finish(self, token, terminated, cleanup_status, continue_run):
        self._proof(terminated, cleanup_status)
        with self._transaction() as db:
            row = self._row(db)
            self._match(row, token)
            if row["lifecycle"] != "cleaning":
                raise LeaseError("INVALID_LEASE_TRANSITION")
            if not terminated or cleanup_status != "completed":
                reason = ("WORKER_NOT_TERMINATED" if not terminated else
                          "CLEANUP_" + cleanup_status.upper())
                db.execute("""UPDATE device_lease SET lifecycle='recovery_required',
                    recovery_reason=?, updated_at=? WHERE singleton=1""", (reason, _now()))
                return None if continue_run else False
            if continue_run:
                # A cleared attempt must not resurrect the original run token.
                # Rotate the durable fence on every safe item handoff as well.
                db.execute("""UPDATE device_lease SET lifecycle='active', attempt_id='',
                    generation=generation+1, updated_at=? WHERE singleton=1""", (_now(),))
                return _token(self._row(db))
            db.execute("""UPDATE device_lease SET lifecycle='free', run_id='',
                boot_epoch='', attempt_id='', recovery_reason='', updated_at=? WHERE singleton=1""",
                (_now(),))
            return True

    def finish_item(self, token: Token, terminated: bool, cleanup_status: str):
        """Resume this run only after proof; return a new fenced run token."""
        if not token.attempt_id:
            raise LeaseError("ATTEMPT_REQUIRED")
        return self._finish(token, terminated, cleanup_status, continue_run=True)

    def release(self, token: Token, terminated: bool, cleanup_status: str):
        """Release ownership only after revoke and verified cleanup/termination."""
        return self._finish(token, terminated, cleanup_status, continue_run=False)
