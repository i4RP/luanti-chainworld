import json
import sqlite3
import threading


class EventDatabase:
    """SQLite-backed event storage for ChainWorld middleware."""

    def __init__(self, db_path: str = "chainworld.db"):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                game_time INTEGER DEFAULT 0,
                data TEXT NOT NULL,
                committed_to_chain INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS chain_commits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                tx_hash TEXT NOT NULL,
                block_number INTEGER NOT NULL,
                events_merkle_root TEXT NOT NULL,
                event_count INTEGER NOT NULL,
                event_ids TEXT NOT NULL,
                committed_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_events_batch ON events(batch_id);
            CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
            CREATE INDEX IF NOT EXISTS idx_events_committed ON events(committed_to_chain);
            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
        """)
        conn.commit()

    def insert_events(self, batch_id: str, events: list[dict]) -> int:
        conn = self._get_conn()
        inserted = 0
        for event in events:
            conn.execute(
                """INSERT INTO events (batch_id, event_type, timestamp, game_time, data)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    batch_id,
                    event["type"],
                    event["timestamp"],
                    event.get("game_time", 0),
                    json.dumps(event["data"]),
                ),
            )
            inserted += 1
        conn.commit()
        return inserted

    def get_pending_events(self, limit: int = 500) -> list[dict]:
        conn = self._get_conn()
        cursor = conn.execute(
            """SELECT id, batch_id, event_type, timestamp, game_time, data
               FROM events WHERE committed_to_chain = 0
               ORDER BY id ASC LIMIT ?""",
            (limit,),
        )
        rows = cursor.fetchall()
        return [
            {
                "id": row["id"],
                "batch_id": row["batch_id"],
                "event_type": row["event_type"],
                "timestamp": row["timestamp"],
                "game_time": row["game_time"],
                "data": json.loads(row["data"]),
            }
            for row in rows
        ]

    def mark_events_committed(self, event_ids: list[int]) -> None:
        conn = self._get_conn()
        placeholders = ",".join(["?"] * len(event_ids))
        conn.execute(
            f"UPDATE events SET committed_to_chain = 1 WHERE id IN ({placeholders})",
            event_ids,
        )
        conn.commit()

    def record_chain_commit(
        self,
        batch_id: str,
        tx_hash: str,
        block_number: int,
        merkle_root: str,
        event_count: int,
        event_ids: list[int],
    ) -> None:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO chain_commits
               (batch_id, tx_hash, block_number, events_merkle_root, event_count, event_ids)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (batch_id, tx_hash, block_number, merkle_root, event_count, json.dumps(event_ids)),
        )
        conn.commit()

    def get_stats(self) -> dict:
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        committed = conn.execute(
            "SELECT COUNT(*) FROM events WHERE committed_to_chain = 1"
        ).fetchone()[0]
        pending = total - committed

        last_commit = conn.execute(
            "SELECT tx_hash, committed_at FROM chain_commits ORDER BY id DESC LIMIT 1"
        ).fetchone()

        return {
            "total_events_received": total,
            "total_events_committed": committed,
            "pending_events": pending,
            "last_commit_tx": last_commit["tx_hash"] if last_commit else "",
            "last_commit_time": last_commit["committed_at"] if last_commit else "",
        }

    def query_events(
        self,
        event_type: str | None = None,
        player: str | None = None,
        since_timestamp: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        conn = self._get_conn()
        conditions = []
        params: list = []

        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if since_timestamp:
            conditions.append("timestamp >= ?")
            params.append(since_timestamp)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = f"""SELECT id, batch_id, event_type, timestamp, game_time, data, committed_to_chain
                    FROM events {where_clause}
                    ORDER BY id DESC LIMIT ? OFFSET ?"""
        params.extend([limit, offset])

        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

        results = []
        for row in rows:
            event_data = json.loads(row["data"])
            # Filter by player if specified
            if player and event_data.get("player") != player:
                continue
            results.append(
                {
                    "id": row["id"],
                    "batch_id": row["batch_id"],
                    "event_type": row["event_type"],
                    "timestamp": row["timestamp"],
                    "game_time": row["game_time"],
                    "data": event_data,
                    "committed_to_chain": bool(row["committed_to_chain"]),
                }
            )

        return results

    def get_chain_commits(self, limit: int = 50) -> list[dict]:
        conn = self._get_conn()
        cursor = conn.execute(
            """SELECT batch_id, tx_hash, block_number, events_merkle_root,
                      event_count, committed_at
               FROM chain_commits ORDER BY id DESC LIMIT ?""",
            (limit,),
        )
        return [
            {
                "batch_id": row["batch_id"],
                "tx_hash": row["tx_hash"],
                "block_number": row["block_number"],
                "events_merkle_root": row["events_merkle_root"],
                "event_count": row["event_count"],
                "committed_at": row["committed_at"],
            }
            for row in cursor.fetchall()
        ]
