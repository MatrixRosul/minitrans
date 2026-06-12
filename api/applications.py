# Job applications from vacancies.html.
# POST (public): submit a job application with optional file attachments.
# GET  (admin):  list all applications.
# DELETE (admin): delete an application by ?id=.
import base64
import os
import random
import re
import string
import sys
import time
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "_lib"))
import db  # noqa: E402
import mail  # noqa: E402
import util  # noqa: E402

ALLOWED_MIMES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/jpeg",
    "image/png",
}
MAX_FILES = 3
MAX_FILE_BYTES = 3 * 1024 * 1024  # 3 MB per file


def _safe_filename(name):
    """Keep only safe characters; fall back to 'file' if nothing remains."""
    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "", str(name or ""))
    return cleaned or "file"


def _guard(fn):
    def wrapped(self):
        try:
            fn(self)
        except db.NotConfigured:
            util.send_json(self, 503, {"error": "store-not-configured"})
        except Exception as e:  # noqa: BLE001 — log details, never leak them to the public
            print("[applications error] %s: %s" % (fn.__name__, e))
            util.send_json(self, 500, {"error": "Внутрішня помилка сервера"})

    return wrapped


class handler(BaseHTTPRequestHandler):
    @_guard
    def do_POST(self):
        body = util.read_json(self)

        # honeypot — bots fill the hidden website field
        if body.get("website"):
            util.send_json(self, 200, {"ok": True})
            return

        # validate required fields
        name = str(body.get("name") or "").strip()[:200]
        phone = str(body.get("phone") or "").strip()[:40]
        if not name or not phone:
            util.send_json(self, 400, {"error": "Вкажіть ім'я і телефон"})
            return

        # optional fields
        email = str(body.get("email") or "").strip()
        if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            util.send_json(self, 400, {"error": "Невірна пошта"})
            return
        if email and util.email_blocked(email):
            util.send_json(self, 400, {"error": "Пошти на російських доменах не приймаються"})
            return

        comment = str(body.get("comment") or "").strip()[:2000]
        position = str(body.get("position") or "").strip()[:200]

        # rate limit: max 3 applications from the same phone in 24 h
        if db.count_applications_since(phone, db.now_ms() - 24 * 3600 * 1000) >= 3:
            util.send_json(
                self, 429,
                {"error": "Забагато заявок з цього номера. Зателефонуйте нам, будь ласка."},
            )
            return

        # validate files
        raw_files = body.get("files") or []
        if not isinstance(raw_files, list):
            raw_files = []
        if len(raw_files) > MAX_FILES:
            util.send_json(self, 400, {"error": "Максимум 3 файли"})
            return

        decoded_files = []
        for f in raw_files:
            fname = _safe_filename(f.get("name") or "")
            mime = str(f.get("type") or "").strip()
            if mime not in ALLOWED_MIMES:
                util.send_json(self, 400, {"error": "Дозволені файли: PDF, DOC, DOCX, JPG, PNG"})
                return
            raw_b64 = str(f.get("data") or "")
            try:
                data = base64.b64decode(raw_b64)
            except Exception:
                util.send_json(self, 400, {"error": "Пошкоджений файл"})
                return
            if len(data) > MAX_FILE_BYTES:
                util.send_json(self, 413, {"error": "Файл завеликий (макс 3МБ)"})
                return
            decoded_files.append((fname, mime, data))

        # create application record
        app_id = "%x%s" % (
            int(time.time() * 1000),
            "".join(random.choices(string.ascii_lowercase + string.digits, k=6)),
        )
        app = {
            "id": app_id,
            "name": name,
            "position": position,
            "phone": phone,
            "email": email,
            "comment": comment,
        }
        db.insert_application(app)

        files_meta = []
        for fname, mime, data in decoded_files:
            file_id = "%x%s" % (
                int(time.time() * 1000),
                "".join(random.choices(string.ascii_lowercase + string.digits, k=6)),
            )
            db.insert_application_file(file_id, app_id, fname, mime, data)
            files_meta.append({"name": fname})

        # send emails (failures are logged, never raise)
        if email:
            mail.application_received(app)
        mail.notify_company_application(app, files_meta)

        util.send_json(self, 200, {"ok": True})

    @_guard
    def do_GET(self):
        if not util.is_authed(self):
            util.send_json(self, 401, {"error": "unauthorized"})
            return
        if db.mode() == "none":
            util.send_json(self, 503, {"error": "store-not-configured"})
            return
        util.send_json(self, 200, {"applications": db.list_applications()})

    @_guard
    def do_DELETE(self):
        if not util.is_authed(self):
            util.send_json(self, 401, {"error": "unauthorized"})
            return
        app_id = util.get_query(self).get("id")
        if not app_id or not db.delete_application(app_id):
            util.send_json(self, 404, {"error": "not found"})
            return
        util.send_json(self, 200, {"ok": True})
