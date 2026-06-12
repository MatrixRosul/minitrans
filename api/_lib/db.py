# Postgres access layer (pg8000, pure-python driver).
# Connection URL resolution:
#   1. DATABASE_URL / POSTGRES_URL env (production: Neon/Vercel Postgres, etc.)
#   2. local dev fallback: postgres://<current user>@127.0.0.1:5432/minitrans
# On Vercel without a configured database mode() == "none" and endpoints answer 503,
# so the public site falls back to its static content.
import getpass
import json
import os
import ssl
import threading
import time
from urllib.parse import urlsplit, unquote

_lock = threading.Lock()
_conn = None
_schema_ready = False


def _db_url():
    url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if url:
        return url
    if os.environ.get("VERCEL"):
        return None
    return "postgres://%s@127.0.0.1:5432/minitrans" % getpass.getuser()


def mode():
    return "postgres" if _db_url() else "none"


class NotConfigured(Exception):
    code = 503


def _connect():
    """Connect with retries: Neon's free tier suspends after idle and the
    first connection during wake-up often fails/hangs — retrying for a few
    seconds hides the cold start instead of surfacing a 500."""
    import pg8000.native

    url = _db_url()
    if not url:
        raise NotConfigured("database not configured")
    p = urlsplit(url)
    host = p.hostname or "127.0.0.1"
    local = host in ("127.0.0.1", "localhost", "::1")
    last_err = None
    for attempt in range(3):
        try:
            return pg8000.native.Connection(
                user=unquote(p.username or getpass.getuser()),
                password=unquote(p.password) if p.password else None,
                host=host,
                port=p.port or 5432,
                database=(p.path or "/minitrans").lstrip("/") or "minitrans",
                ssl_context=None if local else ssl.create_default_context(),
                timeout=10,
            )
        except Exception as e:  # noqa: BLE001 — retry only connection establishment
            last_err = e
            if attempt < 2:
                time.sleep(1.5)
    raise last_err


SCHEMA = """
CREATE TABLE IF NOT EXISTS sales_posts (
  id          TEXT PRIMARY KEY,
  title       TEXT NOT NULL,
  specs       TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  price       TEXT NOT NULL DEFAULT '',
  status      TEXT NOT NULL DEFAULT 'available',
  hidden      BOOLEAN NOT NULL DEFAULT FALSE,
  images      TEXT NOT NULL DEFAULT '[]',
  created_at  BIGINT NOT NULL,
  updated_at  BIGINT
);
CREATE TABLE IF NOT EXISTS photos (
  id         TEXT PRIMARY KEY,
  mime       TEXT NOT NULL,
  data       BYTEA NOT NULL,
  created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS applications (
  id         TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  position   TEXT NOT NULL DEFAULT '',
  phone      TEXT NOT NULL,
  email      TEXT NOT NULL DEFAULT '',
  comment    TEXT NOT NULL DEFAULT '',
  created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS application_files (
  id         TEXT PRIMARY KEY,
  app_id     TEXT NOT NULL,
  name       TEXT NOT NULL,
  mime       TEXT NOT NULL,
  data       BYTEA NOT NULL,
  created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS bookings (
  id           TEXT PRIMARY KEY,
  day          DATE NOT NULL,
  hour         SMALLINT NOT NULL,
  company      TEXT NOT NULL,
  phone        TEXT NOT NULL,
  email        TEXT NOT NULL DEFAULT '',
  comment      TEXT NOT NULL DEFAULT '',
  status       TEXT NOT NULL DEFAULT 'pending',
  created_at   BIGINT NOT NULL,
  confirmed_at BIGINT,
  UNIQUE (day, hour)
);
"""


def _ensure(conn):
    global _schema_ready
    if not _schema_ready:
        for stmt in SCHEMA.split(";"):
            if stmt.strip():
                conn.run(stmt)
        _schema_ready = True


def _get_conn():
    """Live connection. A stale warm-serverless socket is detected with a cheap
    SELECT 1 ping, so the actual statement below runs exactly once — a blind
    retry of a non-idempotent INSERT could double-execute it."""
    global _conn
    if _conn is not None:
        try:
            _conn.run("SELECT 1")
            return _conn
        except Exception:
            try:
                _conn.close()
            except Exception:
                pass
            _conn = None
    _conn = _connect()
    _ensure(_conn)
    return _conn


def run(sql, **params):
    """Execute a statement; returns list of rows (tuples) for SELECT ... RETURNING etc."""
    global _conn
    with _lock:
        conn = _get_conn()
        try:
            return conn.run(sql, **params)
        except Exception as e:
            # drop the connection only on socket-level failures; a constraint
            # violation leaves the connection perfectly healthy
            if e.__class__.__name__ == "InterfaceError":
                try:
                    conn.close()
                except Exception:
                    pass
                _conn = None
            raise


def now_ms():
    return int(time.time() * 1000)


# ---- sales posts ----

_COLS = "id, title, specs, description, price, status, hidden, images, created_at"


def _row_to_post(r):
    return {
        "id": r[0],
        "title": r[1],
        "specs": r[2],
        "desc": r[3],
        "price": r[4],
        "status": r[5],
        "hidden": bool(r[6]),
        "images": json.loads(r[7] or "[]"),
        "createdAt": r[8],
    }


def list_posts():
    rows = run("SELECT %s FROM sales_posts ORDER BY created_at DESC" % _COLS)
    return [_row_to_post(r) for r in rows]


def get_post(post_id):
    rows = run("SELECT %s FROM sales_posts WHERE id = :id" % _COLS, id=post_id)
    return _row_to_post(rows[0]) if rows else None


def insert_post(p):
    run(
        "INSERT INTO sales_posts (id, title, specs, description, price, status, hidden, images, created_at)"
        " VALUES (:id, :title, :specs, :description, :price, :status, :hidden, :images, :created_at)",
        id=p["id"],
        title=p["title"],
        specs=p["specs"],
        description=p["desc"],
        price=p["price"],
        status=p["status"],
        hidden=p["hidden"],
        images=json.dumps(p["images"], ensure_ascii=False),
        created_at=p["createdAt"],
    )


def update_post(p):
    run(
        "UPDATE sales_posts SET title=:title, specs=:specs, description=:description, price=:price,"
        " status=:status, hidden=:hidden, images=:images, updated_at=:updated_at WHERE id=:id",
        id=p["id"],
        title=p["title"],
        specs=p["specs"],
        description=p["desc"],
        price=p["price"],
        status=p["status"],
        hidden=p["hidden"],
        images=json.dumps(p["images"], ensure_ascii=False),
        updated_at=now_ms(),
    )


def delete_post(post_id):
    rows = run("DELETE FROM sales_posts WHERE id = :id RETURNING id", id=post_id)
    return bool(rows)


# ---- photos ----

def insert_photo(photo_id, mime, data):
    run(
        "INSERT INTO photos (id, mime, data, created_at) VALUES (:id, :mime, :data, :created_at)",
        id=photo_id,
        mime=mime,
        data=data,
        created_at=now_ms(),
    )


def get_photo(photo_id):
    rows = run("SELECT mime, data FROM photos WHERE id = :id", id=photo_id)
    if not rows:
        return None
    mime, data = rows[0]
    return mime, bytes(data)


# ---- tacho service bookings ----

def _row_to_booking(r):
    return {
        "id": r[0],
        "day": r[1].isoformat() if hasattr(r[1], "isoformat") else str(r[1]),
        "hour": r[2],
        "company": r[3],
        "phone": r[4],
        "email": r[5],
        "comment": r[6],
        "status": r[7],
        "createdAt": r[8],
    }


_BCOLS = "id, day, hour, company, phone, email, comment, status, created_at"


def get_booking(booking_id):
    rows = run("SELECT %s FROM bookings WHERE id = :id" % _BCOLS, id=booking_id)
    return _row_to_booking(rows[0]) if rows else None


def list_bookings(from_day, to_day):
    rows = run(
        "SELECT %s FROM bookings WHERE day >= :f AND day <= :t ORDER BY day, hour" % _BCOLS,
        f=from_day,
        t=to_day,
    )
    return [_row_to_booking(r) for r in rows]


def insert_booking(b, status="pending"):
    """Returns True on success, False if the slot is already taken."""
    try:
        run(
            "INSERT INTO bookings (id, day, hour, company, phone, email, comment, status, created_at)"
            " VALUES (:id, :day, :hour, :company, :phone, :email, :comment, :status, :created_at)",
            status=status if status in ("pending", "confirmed") else "pending",
            id=b["id"],
            day=b["day"],
            hour=b["hour"],
            company=b["company"],
            phone=b["phone"],
            email=b["email"],
            comment=b["comment"],
            created_at=now_ms(),
        )
        return True
    except Exception as e:  # unique_violation → slot taken
        code = e.args[0].get("C") if e.args and isinstance(e.args[0], dict) else None
        if code == "23505" or "23505" in str(e):
            return False
        raise


def confirm_booking(booking_id):
    # status guard: a double-confirm (two admin tabs) must not re-fire the email
    rows = run(
        "UPDATE bookings SET status = 'confirmed', confirmed_at = :ts"
        " WHERE id = :id AND status = 'pending' RETURNING id",
        id=booking_id,
        ts=now_ms(),
    )
    return bool(rows)


# ---- job applications ----

def insert_application(a):
    run(
        "INSERT INTO applications (id, name, position, phone, email, comment, created_at)"
        " VALUES (:id, :name, :position, :phone, :email, :comment, :created_at)",
        id=a["id"],
        name=a["name"],
        position=a["position"],
        phone=a["phone"],
        email=a["email"],
        comment=a["comment"],
        created_at=now_ms(),
    )


def insert_application_file(file_id, app_id, name, mime, data):
    run(
        "INSERT INTO application_files (id, app_id, name, mime, data, created_at)"
        " VALUES (:id, :app_id, :name, :mime, :data, :created_at)",
        id=file_id,
        app_id=app_id,
        name=name,
        mime=mime,
        data=data,
        created_at=now_ms(),
    )


def list_applications():
    apps = [
        {
            "id": r[0], "name": r[1], "position": r[2], "phone": r[3],
            "email": r[4], "comment": r[5], "createdAt": r[6], "files": [],
        }
        for r in run(
            "SELECT id, name, position, phone, email, comment, created_at"
            " FROM applications ORDER BY created_at DESC"
        )
    ]
    by_id = {a["id"]: a for a in apps}
    for r in run("SELECT id, app_id, name, length(data) FROM application_files ORDER BY created_at"):
        if r[1] in by_id:
            by_id[r[1]]["files"].append({"id": r[0], "name": r[2], "size": r[3]})
    return apps


def get_application_file(file_id):
    rows = run("SELECT name, mime, data FROM application_files WHERE id = :id", id=file_id)
    if not rows:
        return None
    name, mime, data = rows[0]
    return name, mime, bytes(data)


def delete_application(app_id):
    run("DELETE FROM application_files WHERE app_id = :id", id=app_id)
    rows = run("DELETE FROM applications WHERE id = :id RETURNING id", id=app_id)
    return bool(rows)


def count_applications_since(phone, since_ms):
    rows = run(
        "SELECT COUNT(*) FROM applications WHERE phone = :p AND created_at > :ts",
        p=phone,
        ts=since_ms,
    )
    return rows[0][0]


def count_active_for_contact(phone, email, from_day):
    rows = run(
        "SELECT COUNT(*) FROM bookings WHERE day >= :f AND (phone = :p OR (:e <> '' AND email = :e))",
        f=from_day,
        p=phone,
        e=email or "",
    )
    return rows[0][0]


def count_pending(from_day):
    rows = run("SELECT COUNT(*) FROM bookings WHERE day >= :f AND status = 'pending'", f=from_day)
    return rows[0][0]


def delete_booking(booking_id):
    rows = run("DELETE FROM bookings WHERE id = :id RETURNING id", id=booking_id)
    return bool(rows)
