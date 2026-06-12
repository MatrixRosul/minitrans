# Tacho-service booking.
# Slots: Mon–Sat, start hours 09:00–17:00 (service till 18:00), 1 client per hour.
# Public GET returns slot statuses only (no client data); admin GET also returns bookings.
# Email notifications: TODO later — for now requests land in the admin panel.
import datetime
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


def cancel_url_for(h, booking_id):
    return "%s/api/cancel?id=%s&t=%s" % (util.base_url(h), booking_id, util.cancel_token(booking_id))

HOURS = list(range(9, 18))  # start hours: 09..17
HORIZON_DAYS = 14
SUNDAY = 6


def _kyiv_now():
    try:
        from zoneinfo import ZoneInfo

        for name in ("Europe/Kyiv", "Europe/Kiev"):  # older tzdata only has the latter
            try:
                return datetime.datetime.now(ZoneInfo(name))
            except Exception:
                continue
    except Exception:
        pass
    return datetime.datetime.utcnow() + datetime.timedelta(hours=3)


def _days(now):
    out = []
    d = now.date()
    while len(out) < HORIZON_DAYS:
        if d.weekday() != SUNDAY:
            out.append(d)
        d += datetime.timedelta(days=1)
    return out


def _slot_grid(now, taken):
    days = _days(now)
    grid = []
    for d in days:
        slots = []
        for h in HOURS:
            if d == now.date() and h <= now.hour:
                status = "past"
            else:
                b = taken.get((d.isoformat(), h))
                status = "free" if b is None else ("busy" if b["status"] == "confirmed" else "pending")
            slots.append({"hour": h, "status": status})
        grid.append({"date": d.isoformat(), "slots": slots})
    return grid


def _guard(fn):
    def wrapped(self):
        try:
            fn(self)
        except db.NotConfigured:
            util.send_json(self, 503, {"error": "store-not-configured"})
        except Exception as e:  # noqa: BLE001 — log details, never leak them to the public
            print("[bookings error] %s: %s" % (fn.__name__, e))
            util.send_json(self, 500, {"error": "Внутрішня помилка сервера"})

    return wrapped


class handler(BaseHTTPRequestHandler):
    @_guard
    def do_GET(self):
        if db.mode() == "none":
            util.send_json(self, 503, {"error": "store-not-configured"})
            return
        now = _kyiv_now()
        days = _days(now)
        bookings = db.list_bookings(days[0].isoformat(), days[-1].isoformat())
        taken = {(b["day"], b["hour"]): b for b in bookings}
        payload = {"days": _slot_grid(now, taken), "hours": HOURS, "today": now.date().isoformat()}
        if util.is_authed(self):
            payload["bookings"] = bookings
        util.send_json(self, 200, payload)

    @_guard
    def do_POST(self):
        body = util.read_json(self)
        if body.get("website"):  # honeypot field — bots fill it, humans never see it
            util.send_json(self, 200, {"ok": True})
            return
        company = str(body.get("company") or "").strip()[:200]
        phone = str(body.get("phone") or "").strip()[:40]
        email = str(body.get("email") or "").strip()[:200]
        comment = str(body.get("comment") or "").strip()[:500]
        date_s = str(body.get("date") or "")
        hour = body.get("hour")

        if not company or not phone:
            util.send_json(self, 400, {"error": "Вкажіть назву фірми і телефон"})
            return
        if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            util.send_json(self, 400, {"error": "Невірна пошта"})
            return
        if not isinstance(hour, int) or hour not in HOURS or not re.match(r"^\d{4}-\d{2}-\d{2}$", date_s):
            util.send_json(self, 400, {"error": "Невірний слот"})
            return
        try:
            day = datetime.date.fromisoformat(date_s)
        except ValueError:
            util.send_json(self, 400, {"error": "Невірна дата"})
            return

        now = _kyiv_now()
        valid_days = _days(now)
        if day not in valid_days or (day == now.date() and hour <= now.hour):
            util.send_json(self, 400, {"error": "Цей час недоступний для запису"})
            return

        # anti-abuse: cap active bookings per contact and total open requests
        today_iso = now.date().isoformat()
        if db.count_active_for_contact(phone, email, today_iso) >= 3:
            util.send_json(
                self, 429,
                {"error": "З цими контактами вже є кілька активних записів. Зателефонуйте нам, будь ласка."},
            )
            return
        if db.count_pending(today_iso) >= 40:
            util.send_json(
                self, 429,
                {"error": "Онлайн-запис тимчасово перевантажений. Зателефонуйте нам, будь ласка."},
            )
            return

        booking = {
            "id": "%x%s" % (int(time.time() * 1000), "".join(random.choices(string.ascii_lowercase + string.digits, k=6))),
            "day": day,
            "hour": hour,
            "company": company,
            "phone": phone,
            "email": email,
            "comment": comment,
        }
        if not db.insert_booking(booking):
            util.send_json(self, 409, {"error": "Цю годину щойно зайняли. Оберіть іншу."})
            return
        b = dict(booking, day=date_s, status="pending")
        cancel_url = cancel_url_for(self, booking["id"])
        mail.booking_received(b, cancel_url)
        mail.notify_company(b, "new")
        util.send_json(self, 200, {"ok": True, "date": date_s, "hour": hour})

    @_guard
    def do_PUT(self):
        if not util.is_authed(self):
            util.send_json(self, 401, {"error": "unauthorized"})
            return
        booking_id = util.read_json(self).get("id") or util.get_query(self).get("id")
        booking = db.get_booking(booking_id) if booking_id else None
        if not booking:
            util.send_json(self, 404, {"error": "not found"})
            return
        if not db.confirm_booking(booking_id):
            # already confirmed (double-click / second tab) — idempotent, no email re-send
            util.send_json(self, 200, {"ok": True, "already": True})
            return
        sent = mail.booking_confirmed(booking, cancel_url_for(self, booking_id))
        util.send_json(self, 200, {"ok": True, "emailSent": sent})

    @_guard
    def do_DELETE(self):
        if not util.is_authed(self):
            util.send_json(self, 401, {"error": "unauthorized"})
            return
        q = util.get_query(self)
        booking_id = q.get("id")
        reason = (q.get("reason") or "").strip()[:300]
        booking = db.get_booking(booking_id) if booking_id else None
        if not booking or not db.delete_booking(booking_id):
            util.send_json(self, 404, {"error": "not found"})
            return
        sent = mail.booking_cancelled(booking, by_client=False, reason=reason)
        util.send_json(self, 200, {"ok": True, "emailSent": sent})
