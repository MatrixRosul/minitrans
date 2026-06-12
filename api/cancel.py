# Client-side booking cancellation via the signed link from their email.
# GET /api/cancel?id=<booking_id>&t=<hmac token> → cancels and frees the slot.
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "_lib"))
import db  # noqa: E402
import mail  # noqa: E402
import util  # noqa: E402

PAGE = """<!doctype html>
<html lang="uk">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>%(title)s — МПП Мінітранс</title>
<meta name="robots" content="noindex" />
</head>
<body style="margin:0;font-family:Arial,Helvetica,sans-serif;background:#f8fafc;display:flex;align-items:center;justify-content:center;min-height:100vh;padding:20px">
<div style="max-width:440px;background:#fff;border:1px solid #e2e8f0;border-radius:18px;padding:32px;text-align:center">
<div style="font-size:44px;margin-bottom:10px">%(icon)s</div>
<h1 style="font-size:22px;color:#12346a;margin:0 0 10px">%(title)s</h1>
<p style="color:#475569;line-height:1.55;margin:0 0 20px">%(text)s</p>
<a href="/booking.html" style="background:#1b5fd1;color:#fff;text-decoration:none;padding:12px 24px;border-radius:999px;font-weight:600;display:inline-block">Обрати інший час</a>
</div>
</body>
</html>"""


def _page(h, status, icon, title, text):
    body = (PAGE % {"icon": icon, "title": title, "text": text}).encode("utf-8")
    h.send_response(status)
    h.send_header("Content-Type", "text/html; charset=utf-8")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            q = util.get_query(self)
            booking_id = q.get("id", "")
            token = q.get("t", "")
            if not util.check_cancel_token(booking_id, token):
                _page(self, 400, "⚠️", "Посилання недійсне", "Перевірте посилання з листа або зателефонуйте нам.")
                return
            booking = db.get_booking(booking_id)
            if not booking:
                _page(
                    self, 200, "ℹ️", "Запис уже скасовано",
                    "Цей запис не знайдено — можливо, його вже скасували раніше.",
                )
                return
            if not db.delete_booking(booking_id):
                # raced with another cancel/admin delete — don't double-send emails
                _page(
                    self, 200, "ℹ️", "Запис уже скасовано",
                    "Цей запис не знайдено — можливо, його вже скасували раніше.",
                )
                return
            mail.booking_cancelled(booking, by_client=True)
            mail.notify_company(booking, "client_cancelled")
            when = mail.slot_text(booking["day"], booking["hour"])
            _page(
                self, 200, "✅", "Запис скасовано",
                "Ваш запис на %s скасовано, година знову вільна. Чекаємо на вас іншим разом!" % when,
            )
        except db.NotConfigured:
            _page(self, 503, "⚠️", "Сервіс недоступний", "Спробуйте пізніше або зателефонуйте нам.")
        except Exception as e:  # noqa: BLE001 — log details, show a generic page
            print("[cancel error] %s" % e)
            _page(self, 500, "⚠️", "Помилка", "Щось пішло не так. Зателефонуйте нам, будь ласка.")
