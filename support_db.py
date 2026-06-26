"""Support ticket database — SQL Server backend (uses shared db.py connection)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from db import get_conn as _conn


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(row, cur) -> Dict:
    return dict(zip([col[0] for col in cur.description], row))


def _rows(rows, cur) -> List[Dict]:
    cols = [col[0] for col in cur.description]
    return [dict(zip(cols, r)) for r in rows]


# ── Schema ────────────────────────────────────────────────

def init_db() -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
        IF OBJECT_ID('tickets', 'U') IS NULL
        BEGIN
            CREATE TABLE tickets (
                id          INT            IDENTITY(1,1) PRIMARY KEY,
                title       NVARCHAR(500)  NOT NULL,
                description NVARCHAR(MAX)  NOT NULL,
                category    NVARCHAR(100)  NOT NULL DEFAULT 'general',
                priority    NVARCHAR(50)   NOT NULL DEFAULT 'medium',
                status      NVARCHAR(50)   NOT NULL DEFAULT 'open',
                created_by  NVARCHAR(200)  NOT NULL,
                assigned_to NVARCHAR(200),
                created_at  NVARCHAR(30)   NOT NULL,
                updated_at  NVARCHAR(30)   NOT NULL
            )
        END
        """)
        cur.execute("""
        IF OBJECT_ID('ticket_comments', 'U') IS NULL
        BEGIN
            CREATE TABLE ticket_comments (
                id         INT            IDENTITY(1,1) PRIMARY KEY,
                ticket_id  INT            NOT NULL REFERENCES tickets(id),
                author     NVARCHAR(200)  NOT NULL,
                body       NVARCHAR(MAX)  NOT NULL,
                created_at NVARCHAR(30)   NOT NULL
            )
        END
        """)
        cur.execute("""
        IF OBJECT_ID('ticket_attachments', 'U') IS NULL
        BEGIN
            CREATE TABLE ticket_attachments (
                id         INT            IDENTITY(1,1) PRIMARY KEY,
                ticket_id  INT            NOT NULL REFERENCES tickets(id),
                comment_id INT,
                filename   NVARCHAR(500)  NOT NULL,
                size       INT            NOT NULL,
                file_data  VARBINARY(MAX) NOT NULL,
                created_by NVARCHAR(200)  NOT NULL,
                created_at NVARCHAR(30)   NOT NULL
            )
        END
        """)


# ── Tickets ──────────────────────────────────────────────

def create_ticket(title: str, description: str, category: str,
                  priority: str, created_by: str) -> int:
    now = _now()
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO tickets "
            "(title,description,category,priority,status,created_by,created_at,updated_at) "
            "OUTPUT INSERTED.id "
            "VALUES (?,?,?,?,?,?,?,?)",
            title, description, category, priority, "open", created_by, now, now,
        )
        return int(cur.fetchone()[0])


def list_tickets(user: str, is_admin: bool,
                 status: str = "", category: str = "", priority: str = "") -> List[Dict]:
    q = "SELECT * FROM tickets WHERE 1=1"
    args: list = []
    if not is_admin:
        q += " AND created_by=?"; args.append(user)
    if status:
        q += " AND status=?"; args.append(status)
    if category:
        q += " AND category=?"; args.append(category)
    if priority:
        q += " AND priority=?"; args.append(priority)
    q += " ORDER BY updated_at DESC"
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(q, args) if args else cur.execute(q)
        return _rows(cur.fetchall(), cur)


def get_ticket(tid: int) -> Optional[Dict]:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM tickets WHERE id=?", tid)
        row = cur.fetchone()
        return _row(row, cur) if row else None


def update_ticket(tid: int, **fields) -> bool:
    allowed = {"title", "description", "category", "priority", "status", "assigned_to"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    updates["updated_at"] = _now()
    cols = ", ".join(f"{k}=?" for k in updates)
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE tickets SET {cols} WHERE id=?", (*updates.values(), tid))
    return True


def get_stats(user: str, is_admin: bool) -> Dict:
    """Return ticket statistics.

    Admin sees all tickets; non-admin sees only their own.
    """
    user_filter = "" if is_admin else " AND created_by=?"
    user_args   = [] if is_admin else [user]

    statuses   = ("open", "in_progress", "resolved", "closed")
    priorities = ("urgent", "high", "medium", "low")

    with _conn() as conn:
        cur = conn.cursor()

        # ── by_status ──
        by_status: Dict[str, int] = {s: 0 for s in statuses}
        cur.execute(
            f"SELECT status, COUNT(*) FROM tickets WHERE 1=1{user_filter} GROUP BY status",
            user_args,
        ) if user_args else cur.execute(
            "SELECT status, COUNT(*) FROM tickets GROUP BY status"
        )
        for row in cur.fetchall():
            st, cnt = row[0], row[1]
            if st in by_status:
                by_status[st] = cnt

        # ── by_category (top 6) ──
        cur.execute(
            f"SELECT TOP 6 category, COUNT(*) AS cnt FROM tickets "
            f"WHERE 1=1{user_filter} GROUP BY category ORDER BY cnt DESC",
            user_args,
        ) if user_args else cur.execute(
            "SELECT TOP 6 category, COUNT(*) AS cnt FROM tickets "
            "GROUP BY category ORDER BY cnt DESC"
        )
        by_category: Dict[str, int] = {row[0]: row[1] for row in cur.fetchall()}

        # ── by_priority (active only: open + in_progress) ──
        by_priority: Dict[str, int] = {p: 0 for p in priorities}
        active_filter = (
            f"WHERE status IN ('open','in_progress'){' AND created_by=?' if not is_admin else ''}"
        )
        cur.execute(
            f"SELECT priority, COUNT(*) FROM tickets {active_filter} GROUP BY priority",
            user_args,
        ) if user_args else cur.execute(
            "SELECT priority, COUNT(*) FROM tickets "
            "WHERE status IN ('open','in_progress') GROUP BY priority"
        )
        for row in cur.fetchall():
            pr, cnt = row[0], row[1]
            if pr in by_priority:
                by_priority[pr] = cnt

        # ── total ──
        cur.execute(
            f"SELECT COUNT(*) FROM tickets WHERE 1=1{user_filter}",
            user_args,
        ) if user_args else cur.execute("SELECT COUNT(*) FROM tickets")
        total = int(cur.fetchone()[0])

    return {
        "by_status":   by_status,
        "by_category": by_category,
        "by_priority": by_priority,
        "total":       total,
    }


# ── Comments ─────────────────────────────────────────────

def add_comment(ticket_id: int, author: str, body: str) -> int:
    now = _now()
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO ticket_comments (ticket_id,author,body,created_at) "
            "OUTPUT INSERTED.id "
            "VALUES (?,?,?,?)",
            ticket_id, author, body, now,
        )
        cid = int(cur.fetchone()[0])
        cur.execute("UPDATE tickets SET updated_at=? WHERE id=?", now, ticket_id)
        return cid


def list_comments(ticket_id: int) -> List[Dict]:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM ticket_comments WHERE ticket_id=? ORDER BY created_at",
            ticket_id,
        )
        return _rows(cur.fetchall(), cur)


# ── Attachments ───────────────────────────────────────────

def save_attachment(ticket_id: int, comment_id: Optional[int],
                    filename: str, data: bytes, created_by: str) -> int:
    now = _now()
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO ticket_attachments "
            "(ticket_id,comment_id,filename,size,file_data,created_by,created_at) "
            "OUTPUT INSERTED.id "
            "VALUES (?,?,?,?,?,?,?)",
            ticket_id, comment_id, filename, len(data), data, created_by, now,
        )
        return int(cur.fetchone()[0])


def list_attachments(ticket_id: int) -> List[Dict]:
    """Returns attachment metadata without file_data (avoid loading large blobs)."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id,ticket_id,comment_id,filename,size,created_by,created_at "
            "FROM ticket_attachments WHERE ticket_id=? ORDER BY created_at",
            ticket_id,
        )
        return _rows(cur.fetchall(), cur)


def get_attachment(attachment_id: int) -> Optional[Dict]:
    """Returns attachment metadata without file_data."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id,ticket_id,comment_id,filename,size,created_by,created_at "
            "FROM ticket_attachments WHERE id=?",
            attachment_id,
        )
        row = cur.fetchone()
        return _row(row, cur) if row else None


def get_attachment_bytes(attachment_id: int) -> Optional[bytes]:
    """Returns the raw file bytes for an attachment."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT file_data FROM ticket_attachments WHERE id=?",
            attachment_id,
        )
        row = cur.fetchone()
        return bytes(row[0]) if row else None


# ── VPN Configs ───────────────────────────────────────────

def init_vpn_table() -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
        IF OBJECT_ID('vpn_configs', 'U') IS NULL
        BEGIN
            CREATE TABLE vpn_configs (
                id          INT            IDENTITY(1,1) PRIMARY KEY,
                name        NVARCHAR(200)  NOT NULL,
                filename    NVARCHAR(500)  NOT NULL,
                assigned_to NVARCHAR(200)  NOT NULL,
                file_data   VARBINARY(MAX) NOT NULL,
                uploaded_by NVARCHAR(200)  NOT NULL,
                created_at  NVARCHAR(30)   NOT NULL
            )
        END
        """)


def upload_vpn_config(name: str, filename: str, assigned_to: str,
                      file_data: bytes, uploaded_by: str) -> int:
    now = _now()
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO vpn_configs (name,filename,assigned_to,file_data,uploaded_by,created_at) "
            "OUTPUT INSERTED.id VALUES (?,?,?,?,?,?)",
            name, filename, assigned_to, file_data, uploaded_by, now,
        )
        return int(cur.fetchone()[0])


def list_vpn_configs(user: str, is_admin: bool) -> List[Dict]:
    with _conn() as conn:
        cur = conn.cursor()
        if is_admin:
            cur.execute(
                "SELECT id,name,filename,assigned_to,uploaded_by,created_at "
                "FROM vpn_configs ORDER BY created_at DESC"
            )
        else:
            cur.execute(
                "SELECT id,name,filename,assigned_to,uploaded_by,created_at "
                "FROM vpn_configs WHERE assigned_to=? ORDER BY created_at DESC",
                user,
            )
        return _rows(cur.fetchall(), cur)


def get_vpn_config(cid: int) -> Optional[Dict]:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id,name,filename,assigned_to,uploaded_by,created_at "
            "FROM vpn_configs WHERE id=?",
            cid,
        )
        row = cur.fetchone()
        return _row(row, cur) if row else None


def get_vpn_config_bytes(cid: int) -> Optional[bytes]:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT file_data FROM vpn_configs WHERE id=?", cid)
        row = cur.fetchone()
        return bytes(row[0]) if row else None


def delete_vpn_config(cid: int) -> bool:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM vpn_configs WHERE id=?", cid)
        return cur.rowcount > 0


# ── Workstation Centers ───────────────────────────────────

def init_workstations_tables() -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
        IF OBJECT_ID('workstation_centers', 'U') IS NULL
        BEGIN
            CREATE TABLE workstation_centers (
                id         INT           IDENTITY(1,1) PRIMARY KEY,
                name       NVARCHAR(200) NOT NULL,
                location   NVARCHAR(500),
                created_at NVARCHAR(30)  NOT NULL
            )
        END
        """)
        cur.execute("""
        IF OBJECT_ID('workstations', 'U') IS NULL
        BEGIN
            CREATE TABLE workstations (
                id            INT           IDENTITY(1,1) PRIMARY KEY,
                center_id     INT           NOT NULL REFERENCES workstation_centers(id),
                name          NVARCHAR(200) NOT NULL,
                ip            NVARCHAR(50),
                os_type       NVARCHAR(50)  NOT NULL DEFAULT 'windows',
                assigned_user NVARCHAR(200),
                ram_gb        INT,
                cpu_model     NVARCHAR(200),
                disk_gb       INT,
                notes         NVARCHAR(MAX),
                created_at    NVARCHAR(30)  NOT NULL,
                updated_at    NVARCHAR(30)  NOT NULL
            )
        END
        """)


def list_centers() -> List[Dict]:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT c.id, c.name, c.location, c.created_at,
                   COUNT(w.id) AS workstation_count
            FROM workstation_centers c
            LEFT JOIN workstations w ON w.center_id = c.id
            GROUP BY c.id, c.name, c.location, c.created_at
            ORDER BY c.name
        """)
        cols = ['id', 'name', 'location', 'created_at', 'workstation_count']
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def create_center(name: str, location: str) -> int:
    now = _now()
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO workstation_centers(name,location,created_at) OUTPUT INSERTED.id VALUES(?,?,?)",
            name, location or '', now
        )
        return int(cur.fetchone()[0])


def update_center(cid: int, name: str, location: str) -> bool:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE workstation_centers SET name=?,location=? WHERE id=?",
            name, location or '', cid
        )
        return cur.rowcount > 0


def delete_center(cid: int) -> bool:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM workstations WHERE center_id=?", cid)
        cur.execute("DELETE FROM workstation_centers WHERE id=?", cid)
        return True


def list_workstations(center_id: Optional[int] = None) -> List[Dict]:
    with _conn() as conn:
        cur = conn.cursor()
        if center_id:
            cur.execute("SELECT * FROM workstations WHERE center_id=? ORDER BY name", center_id)
        else:
            cur.execute("SELECT * FROM workstations ORDER BY center_id, name")
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def create_workstation(center_id: int, name: str, ip: str, os_type: str,
                       assigned_user: str, ram_gb, cpu_model: str, disk_gb, notes: str) -> int:
    now = _now()
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO workstations(center_id,name,ip,os_type,assigned_user,ram_gb,cpu_model,disk_gb,notes,created_at,updated_at) "
            "OUTPUT INSERTED.id VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            center_id, name, ip or None, os_type or 'windows',
            assigned_user or None, ram_gb or None, cpu_model or None,
            disk_gb or None, notes or None, now, now
        )
        return int(cur.fetchone()[0])


def update_workstation(wid: int, **fields) -> bool:
    allowed = {'center_id', 'name', 'ip', 'os_type', 'assigned_user', 'ram_gb', 'cpu_model', 'disk_gb', 'notes'}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    updates['updated_at'] = _now()
    cols = ', '.join(f"{k}=?" for k in updates)
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE workstations SET {cols} WHERE id=?", (*updates.values(), wid))
        return cur.rowcount > 0


def delete_workstation(wid: int) -> bool:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM workstations WHERE id=?", wid)
        return cur.rowcount > 0
