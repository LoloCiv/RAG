"""Persistencia transaccional para eventos y correo compartido.

SQLite con WAL alcanza para el piloto de cinco personas y evita que los JSON
locales pierdan actualizaciones cuando n8n y la interfaz escriben a la vez.
"""

import json
import re
import sqlite3
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.agent.queries import load_query
from app.config import QUERIES_DIR


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    if not slug:
        raise ValueError("El nombre del evento debe contener letras o numeros")
    return slug


class EventStore:
    """Guarda la memoria del evento y conserva el origen de cada dato."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        # SQLite lower() no cubre tildes; la búsqueda debe servir en español.
        connection.create_function("casefold", 1, lambda value: (value or "").casefold(), deterministic=True)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK(status IN ('active', 'archived')),
                    created_at TEXT NOT NULL,
                    archived_at TEXT
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    external_message_id TEXT NOT NULL UNIQUE,
                    account_email TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    recipients_json TEXT NOT NULL,
                    cc_json TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body_text TEXT NOT NULL,
                    labels_json TEXT NOT NULL,
                    attachments_json TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    thread_url TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS event_messages (
                    event_id TEXT NOT NULL REFERENCES events(id),
                    message_id TEXT NOT NULL UNIQUE REFERENCES messages(id),
                    association_state TEXT NOT NULL CHECK(association_state IN ('suggested', 'confirmed')),
                    reason TEXT NOT NULL,
                    confirmed_by TEXT,
                    confirmed_at TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(event_id, message_id)
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    event_id TEXT REFERENCES events(id),
                    message_id TEXT REFERENCES messages(id),
                    actor_email TEXT NOT NULL,
                    event_name TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS event_query_links (
                    event_id TEXT NOT NULL REFERENCES events(id),
                    query_id TEXT NOT NULL,
                    saved_by TEXT NOT NULL,
                    saved_at TEXT NOT NULL,
                    PRIMARY KEY(event_id, query_id)
                );
                CREATE INDEX IF NOT EXISTS idx_event_message_state
                    ON event_messages(event_id, association_state);
                CREATE INDEX IF NOT EXISTS idx_message_thread
                    ON messages(account_email, thread_id);
                """
            )

    def last_email_received_at(self) -> str | None:
        """Fecha de incorporación local, independiente de la antigüedad del correo."""
        with self._connect() as connection:
            return connection.execute("SELECT MAX(created_at) FROM messages").fetchone()[0]

    def create_event(self, name: str) -> dict:
        """Crea un evento activo; repetir el nombre devuelve el mismo registro."""
        slug = _slugify(name)
        with self._connect() as connection:
            existing = connection.execute("SELECT * FROM events WHERE slug = ?", (slug,)).fetchone()
            if existing:
                return self._event_dict(existing)
            record = {
                "id": uuid.uuid4().hex,
                "name": name.strip(),
                "slug": slug,
                "status": "active",
                "created_at": _now(),
                "archived_at": None,
            }
            connection.execute(
                "INSERT INTO events(id, name, slug, status, created_at, archived_at) VALUES (:id, :name, :slug, :status, :created_at, :archived_at)",
                record,
            )
            self._audit(connection, event_id=record["id"], actor_email="system", event_name="event_created")
            return record

    def list_events(self, include_archived: bool = False) -> list[dict]:
        query = "SELECT * FROM events"
        if not include_archived:
            query += " WHERE status = 'active'"
        query += " ORDER BY created_at DESC"
        with self._connect() as connection:
            return [self._event_dict(row) for row in connection.execute(query)]

    def archive_event(self, event_id: str, actor_email: str) -> None:
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE events SET status = 'archived', archived_at = ? WHERE id = ? AND status = 'active'",
                (_now(), event_id),
            ).rowcount
            if not changed:
                raise ValueError("No existe un evento activo con ese id")
            self._audit(connection, event_id=event_id, actor_email=actor_email, event_name="event_archived")

    def ingest_email(self, payload: dict) -> dict:
        """Guarda un email idempotentemente y sugiere un evento desde la etiqueta."""
        required = {
            "external_message_id", "account_email", "thread_id", "sender", "recipients",
            "cc", "subject", "body_text", "labels", "attachments", "received_at",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ValueError("Faltan campos de correo: " + ", ".join(missing))
        for key in ("recipients", "cc", "labels", "attachments"):
            if not isinstance(payload[key], list):
                raise ValueError(f"{key} debe ser una lista")

        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM messages WHERE external_message_id = ?", (payload["external_message_id"],)
            ).fetchone()
            if existing:
                return self._message_with_suggestion(connection, existing)

            record = {
                "id": uuid.uuid4().hex,
                "external_message_id": payload["external_message_id"],
                "account_email": payload["account_email"].lower().strip(),
                "thread_id": payload["thread_id"],
                "sender": payload["sender"],
                "recipients_json": json.dumps(payload["recipients"], ensure_ascii=False),
                "cc_json": json.dumps(payload["cc"], ensure_ascii=False),
                "subject": payload["subject"],
                "body_text": payload["body_text"],
                "labels_json": json.dumps(payload["labels"], ensure_ascii=False),
                "attachments_json": json.dumps(payload["attachments"], ensure_ascii=False),
                "received_at": payload["received_at"],
                "thread_url": payload.get("thread_url"),
                "created_at": _now(),
            }
            connection.execute(
                """INSERT INTO messages(
                    id, external_message_id, account_email, thread_id, sender, recipients_json,
                    cc_json, subject, body_text, labels_json, attachments_json, received_at,
                    thread_url, created_at
                ) VALUES (
                    :id, :external_message_id, :account_email, :thread_id, :sender, :recipients_json,
                    :cc_json, :subject, :body_text, :labels_json, :attachments_json, :received_at,
                    :thread_url, :created_at
                )""",
                record,
            )
            event = self._event_for_labels(connection, payload["labels"])
            if event:
                connection.execute(
                    """INSERT INTO event_messages(event_id, message_id, association_state, reason, confirmed_by, confirmed_at, created_at)
                    VALUES (?, ?, 'suggested', 'gmail_label', NULL, NULL, ?)""",
                    (event["id"], record["id"], _now()),
                )
                self._audit(connection, event_id=event["id"], message_id=record["id"], actor_email="n8n", event_name="event_suggested", details={"reason": "gmail_label"})
            self._audit(connection, message_id=record["id"], actor_email="n8n", event_name="email_ingested")
            saved = connection.execute("SELECT * FROM messages WHERE id = ?", (record["id"],)).fetchone()
            return self._message_with_suggestion(connection, saved)

    def confirm_event_message(self, event_id: str, message_id: str, actor_email: str) -> None:
        """Convierte una sugerencia en memoria visible del evento o la reasigna."""
        with self._connect() as connection:
            # La validación y la escritura comparten el bloqueo frente a archivo/reasignación.
            connection.execute("BEGIN IMMEDIATE")
            event = connection.execute("SELECT id FROM events WHERE id = ? AND status = 'active'", (event_id,)).fetchone()
            message = connection.execute("SELECT id FROM messages WHERE id = ?", (message_id,)).fetchone()
            if not event or not message:
                raise ValueError("El evento o mensaje no existe, o el evento esta archivado")
            previous = connection.execute(
                "SELECT event_id, association_state FROM event_messages WHERE message_id = ?", (message_id,)
            ).fetchone()
            if previous and previous["event_id"] == event_id and previous["association_state"] == "confirmed":
                return
            connection.execute("DELETE FROM event_messages WHERE message_id = ?", (message_id,))
            connection.execute(
                """INSERT INTO event_messages(event_id, message_id, association_state, reason, confirmed_by, confirmed_at, created_at)
                VALUES (?, ?, 'confirmed', 'human_confirmation', ?, ?, ?)""",
                (event_id, message_id, actor_email, _now(), _now()),
            )
            self._audit(connection, event_id=event_id, message_id=message_id, actor_email=actor_email, event_name="event_confirmed", details={"previous_event_id": previous["event_id"] if previous else None})

    def event_counts(self, event_id: str) -> dict:
        with self._connect() as connection:
            counts = dict(connection.execute(
                "SELECT association_state, COUNT(*) FROM event_messages WHERE event_id = ? GROUP BY association_state",
                (event_id,),
            ).fetchall())
            references = connection.execute("SELECT COUNT(*) FROM event_query_links WHERE event_id = ?", (event_id,)).fetchone()[0]
        return {"confirmed": counts.get("confirmed", 0), "pending": counts.get("suggested", 0), "references": references}

    @staticmethod
    def _page_number(page: int, total: int) -> int:
        return min(max(1, int(page)), max(1, (total + 19) // 20))

    def conversation_filters(self, event_id: str) -> dict:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT DISTINCT m.sender, m.account_email FROM messages m
                JOIN event_messages e ON e.message_id = m.id
                WHERE e.event_id = ? AND e.association_state = 'confirmed'""", (event_id,),
            ).fetchall()
        return {"senders": sorted({r["sender"] for r in rows}), "accounts": sorted({r["account_email"] for r in rows})}

    def list_conversations(
        self, event_id: str, *, search: str = "", sender: str | None = None,
        account_email: str | None = None, date_from: str | None = None,
        date_to: str | None = None, page: int = 1,
    ) -> dict:
        """Filtra hilos por coincidencias y devuelve completos los veinte de la página.

        Las fechas se comparan en UTC y los offsets se normalizan para ordenar.
        Mantener el hilo completo evita presentar una respuesta sin su contexto.
        """
        conditions, params = [], [event_id]
        if search.strip():
            conditions.append("instr(casefold(subject || ' ' || body_text), ?) > 0")
            params.append(search.strip().casefold())
        for field, value in (("sender", sender), ("account_email", account_email)):
            if value:
                conditions.append(f"{field} = ?")
                params.append(value)
        for operator, value in ((">=", date_from), ("<=", date_to)):
            if value:
                conditions.append(f"date(received_at) {operator} date(?)")
                params.append(value)
        matching = " AND ".join(conditions) or "1"
        grouped = f"""WITH scoped AS (
            SELECT m.* FROM messages m JOIN event_messages e ON e.message_id = m.id
            WHERE e.event_id = ? AND e.association_state = 'confirmed'
        ), threads AS (
            SELECT account_email, thread_id, MAX(julianday(received_at)) AS last_activity
            FROM scoped GROUP BY account_email, thread_id
            HAVING MAX(CASE WHEN {matching} THEN 1 ELSE 0 END) = 1
        ) """
        with self._connect() as connection:
            total = connection.execute(grouped + "SELECT COUNT(*) FROM threads", params).fetchone()[0]
            page = self._page_number(page, total)
            threads = connection.execute(
                grouped + "SELECT * FROM threads ORDER BY last_activity DESC, account_email, thread_id LIMIT 20 OFFSET ?",
                [*params, (page - 1) * 20],
            ).fetchall()
            items = []
            for thread in threads:
                rows = connection.execute(
                    """SELECT m.* FROM messages m JOIN event_messages e ON e.message_id = m.id
                    WHERE e.event_id = ? AND e.association_state = 'confirmed'
                    AND m.account_email = ? AND m.thread_id = ?
                    ORDER BY julianday(m.received_at), m.id""",
                    (event_id, thread["account_email"], thread["thread_id"]),
                ).fetchall()
                messages = [self._message_dict(row) for row in rows]
                items.append({"account_email": thread["account_email"], "thread_id": thread["thread_id"], "messages": messages})
        return {"items": items, "total": total, "page": page, "page_size": 20}

    def list_pending_messages(self, event_id: str | None = None, *, page: int = 1) -> dict:
        """Sin evento devuelve únicamente correo sin asociación, para la bandeja general."""
        condition = "e.message_id IS NULL" if event_id is None else "e.event_id = ? AND e.association_state = 'suggested'"
        params = [] if event_id is None else [event_id]
        joined = f"FROM messages m LEFT JOIN event_messages e ON e.message_id = m.id WHERE {condition}"
        with self._connect() as connection:
            total = connection.execute("SELECT COUNT(*) " + joined, params).fetchone()[0]
            page = self._page_number(page, total)
            rows = connection.execute(
                "SELECT m.* " + joined + " ORDER BY julianday(m.received_at) DESC, m.id LIMIT 20 OFFSET ?",
                [*params, (page - 1) * 20],
            ).fetchall()
        return {"items": [self._message_dict(row) for row in rows], "total": total, "page": page, "page_size": 20}

    def link_query(self, event_id: str, query_id: str, actor_email: str, *, queries_dir: Path = QUERIES_DIR) -> None:
        """Vincula evidencia ya guardada, sin duplicar archivos ni modificar la respuesta."""
        if not re.fullmatch(r"[A-Za-z0-9_-]+", query_id) or load_query(query_id, queries_dir) is None:
            raise ValueError("La consulta no existe o no está disponible")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not connection.execute("SELECT id FROM events WHERE id = ? AND status = 'active'", (event_id,)).fetchone():
                raise ValueError("Seleccioná un evento activo")
            changed = connection.execute(
                "INSERT OR IGNORE INTO event_query_links(event_id, query_id, saved_by, saved_at) VALUES (?, ?, ?, ?)",
                (event_id, query_id, actor_email, _now()),
            ).rowcount
            if changed:
                self._audit(connection, event_id=event_id, actor_email=actor_email, event_name="query_linked", details={"query_id": query_id})

    def list_query_links(self, event_id: str) -> list[dict]:
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM event_query_links WHERE event_id = ? ORDER BY saved_at DESC, query_id", (event_id,),
            )]

    def unlink_query(self, event_id: str, query_id: str, actor_email: str) -> None:
        with self._connect() as connection:
            changed = connection.execute("DELETE FROM event_query_links WHERE event_id = ? AND query_id = ?", (event_id, query_id)).rowcount
            if changed:
                self._audit(connection, event_id=event_id, actor_email=actor_email, event_name="query_unlinked", details={"query_id": query_id})

    def list_event_messages(self, event_id: str) -> list[dict]:
        """Devuelve solo asociaciones confirmadas para no mezclar contexto dudoso."""
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT messages.*, event_messages.association_state
                FROM messages JOIN event_messages ON event_messages.message_id = messages.id
                WHERE event_messages.event_id = ? AND event_messages.association_state = 'confirmed'
                ORDER BY messages.received_at ASC""",
                (event_id,),
            )
            return [self._message_dict(row, association_state=row["association_state"]) for row in rows]

    def list_suggested_messages(self, event_id: str) -> list[dict]:
        """Muestra candidatos aparte para que una sugerencia no se vuelva hecho."""
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT messages.*, event_messages.association_state
                FROM messages JOIN event_messages ON event_messages.message_id = messages.id
                WHERE event_messages.event_id = ? AND event_messages.association_state = 'suggested'
                ORDER BY messages.received_at DESC""",
                (event_id,),
            )
            return [self._message_dict(row, association_state=row["association_state"]) for row in rows]

    def count_messages(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0])

    @staticmethod
    def _event_dict(row: sqlite3.Row) -> dict:
        return dict(row)

    def _event_for_labels(self, connection: sqlite3.Connection, labels: list[str]) -> sqlite3.Row | None:
        for label in labels:
            if not isinstance(label, str) or not label.casefold().startswith("evento/"):
                continue
            slug = _slugify(label.split("/", 1)[1])
            event = connection.execute("SELECT * FROM events WHERE slug = ? AND status = 'active'", (slug,)).fetchone()
            if event:
                return event
        return None

    def _message_with_suggestion(self, connection: sqlite3.Connection, row: sqlite3.Row) -> dict:
        association = connection.execute(
            "SELECT event_id, association_state, reason FROM event_messages WHERE message_id = ?", (row["id"],)
        ).fetchone()
        suggestion = None
        if association:
            suggestion = {"event_id": association["event_id"], "state": association["association_state"], "reason": association["reason"]}
        return self._message_dict(row, event_suggestion=suggestion)

    @staticmethod
    def _message_dict(row: sqlite3.Row, event_suggestion: dict | None = None, association_state: str | None = None) -> dict:
        data = dict(row)
        data["recipients"] = json.loads(data.pop("recipients_json"))
        data["cc"] = json.loads(data.pop("cc_json"))
        data["labels"] = json.loads(data.pop("labels_json"))
        data["attachments"] = json.loads(data.pop("attachments_json"))
        if association_state is not None:
            data["association_state"] = association_state
        data["event_suggestion"] = event_suggestion
        return data

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        *,
        actor_email: str,
        event_name: str,
        event_id: str | None = None,
        message_id: str | None = None,
        details: dict | None = None,
    ) -> None:
        connection.execute(
            """INSERT INTO audit_events(id, event_id, message_id, actor_email, event_name, details_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (uuid.uuid4().hex, event_id, message_id, actor_email, event_name, json.dumps(details or {}, ensure_ascii=False), _now()),
        )
