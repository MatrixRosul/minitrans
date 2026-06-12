# Email transport — two options, auto-selected by env:
#   Resend HTTP API  (preferred)  — set RESEND_API_KEY
#   Gmail SMTP       (fallback)   — set GMAIL_APP_PASSWORD
# Additional env:
#   GMAIL_USER          Gmail sender mailbox (default stominitrans@gmail.com)
#   NOTIFY_EMAIL        where new-booking notifications go (default = GMAIL_USER)
#   MAIL_FROM           RFC-5322 From address for Resend (default МПП Мінітранс <booking@minitrans.uz.ua>)
#   REPLY_TO            Reply-To for Resend emails (default = GMAIL_USER)
# Without either transport configured, sending is skipped (logged) — booking flow still works.
# Sends are synchronous and finish before the HTTP response (required on Vercel).
import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

GMAIL_USER = os.environ.get("GMAIL_USER", "stominitrans@gmail.com")
GMAIL_APP_PASSWORD = (os.environ.get("GMAIL_APP_PASSWORD") or "").replace(" ", "")
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", GMAIL_USER)

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
MAIL_FROM = os.environ.get("MAIL_FROM", "МПП Мінітранс <booking@minitrans.uz.ua>")
REPLY_TO = os.environ.get("REPLY_TO", GMAIL_USER)

SITE_NAME = "МПП Мінітранс"
ADDRESS = "МПП Мінітранс, с. Великі Лази, вул. Східна, 4а"
MAPS_URL = (
    "https://www.google.com/maps/search/?api=1&query="
    "%D0%9C%D0%9F%D0%9F%20%D0%9C%D1%96%D0%BD%D1%96%D1%82%D1%80%D0%B0%D0%BD%D1%81%2C%20"
    "%D0%B2%D1%83%D0%BB.%20%D0%A1%D1%85%D1%96%D0%B4%D0%BD%D0%B0%204%D0%B0%2C%20"
    "%D0%92%D0%B5%D0%BB%D0%B8%D0%BA%D1%96%20%D0%9B%D0%B0%D0%B7%D0%B8"
)
TACHO_PHONE = "+38 (073) 001 07 70"

WEEKDAYS_UK = ["понеділок", "вівторок", "середа", "четвер", "п’ятниця", "субота", "неділя"]


def enabled():
    return bool(RESEND_API_KEY) or bool(GMAIL_APP_PASSWORD)


def slot_text(day_iso, hour):
    """'14:00, четвер 12.06.2026'"""
    import datetime

    d = datetime.date.fromisoformat(day_iso)
    return "%02d:00, %s %s" % (hour, WEEKDAYS_UK[d.weekday()], d.strftime("%d.%m.%Y"))


_smtp = None


def _get_smtp():
    """One logged-in SMTP connection per function invocation (two emails per
    booking = one TLS handshake), with liveness check for warm reuse."""
    global _smtp
    if _smtp is not None:
        try:
            _smtp.noop()
            return _smtp
        except Exception:
            try:
                _smtp.quit()
            except Exception:
                pass
            _smtp = None
    s = smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=8)
    s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
    _smtp = s
    return s


def _send_resend(to, subject, text, html):
    """Send via Resend HTTP API. Returns True on 2xx, False otherwise. Never raises."""
    try:
        payload = json.dumps(
            {
                "from": MAIL_FROM,
                "to": [to],
                "subject": subject,
                "html": html,
                "text": text,
                "reply_to": REPLY_TO,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=payload,
            headers={
                "Authorization": "Bearer %s" % RESEND_API_KEY,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
        if 200 <= status < 300:
            return True
        print("[mail error] Resend non-2xx status=%s to=%s subject=%s" % (status, to, subject))
        return False
    except Exception as e:  # noqa: BLE001 — email must never break the booking flow
        print("[mail error] Resend to=%s: %s" % (to, e))
        return False


def send(to, subject, text, html):
    """Returns True if delivered, False otherwise. Never raises."""
    global _smtp
    if not to:
        return False
    if RESEND_API_KEY:
        return _send_resend(to, subject, text, html)
    if GMAIL_APP_PASSWORD:
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = formataddr((SITE_NAME, GMAIL_USER))
            msg["To"] = to
            msg["Subject"] = subject
            msg.attach(MIMEText(text, "plain", "utf-8"))
            msg.attach(MIMEText(html, "html", "utf-8"))
            _get_smtp().sendmail(GMAIL_USER, [to], msg.as_string())
            return True
        except Exception as e:  # noqa: BLE001 — email must never break the booking flow
            print("[mail error] to=%s: %s" % (to, e))
            try:
                if _smtp is not None:
                    _smtp.quit()
            except Exception:
                pass
            _smtp = None
            return False
    print("[mail skipped] to=%s subject=%s\n%s" % (to, subject, text))
    return False


def _wrap_html(title, lines, button=None):
    """Simple branded HTML email. lines: list of paragraphs (may contain <a>/<strong>)."""
    body = "".join('<p style="margin:0 0 12px;line-height:1.55">%s</p>' % l for l in lines)
    btn = ""
    if button:
        btn = (
            '<p style="margin:20px 0"><a href="%s" '
            'style="background:#1b5fd1;color:#fff;text-decoration:none;'
            'padding:12px 22px;border-radius:999px;font-weight:600;display:inline-block">%s</a></p>'
            % (button[1], button[0])
        )
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;background:#f8fafc;padding:24px">'
        '<div style="max-width:560px;margin:0 auto;background:#fff;border-radius:16px;overflow:hidden;'
        'border:1px solid #e2e8f0">'
        '<div style="background:#12346a;color:#fff;padding:18px 24px;font-size:18px;font-weight:700">%s</div>'
        '<div style="padding:24px;color:#1f2937;font-size:15px">%s%s</div>'
        '<div style="padding:16px 24px;background:#f8fafc;color:#64748b;font-size:13px;border-top:1px solid #e2e8f0">'
        "%s · %s · <a href=\"%s\" style=\"color:#1b5fd1\">Показати на карті</a></div>"
        "</div></div>" % (title, body, btn, ADDRESS, TACHO_PHONE, MAPS_URL)
    )


# ---------- booking emails ----------

def booking_received(b, cancel_url):
    """To the client right after they submit a request (status: pending)."""
    when = slot_text(b["day"], b["hour"])
    subject = "Заявку на тахосервіс отримано — %s" % SITE_NAME
    text = (
        "Вітаємо!\n\n"
        "Ми отримали вашу заявку на тахосервіс на %s.\n"
        "Час зарезервовано та очікує підтвердження майстром — ми надішлемо лист, щойно запис буде підтверджено.\n\n"
        "Адреса: %s\nКарта: %s\nТелефон: %s\n\n"
        "Скасувати запис: %s\n" % (when, ADDRESS, MAPS_URL, TACHO_PHONE, cancel_url)
    )
    html = _wrap_html(
        "Заявку отримано ✅",
        [
            "Вітаємо!",
            "Ми отримали вашу заявку на тахосервіс на <strong>%s</strong>." % when,
            "Час зарезервовано та очікує підтвердження майстром — ми надішлемо лист, щойно запис буде підтверджено.",
            'Якщо плани змінилися — <a href="%s" style="color:#1b5fd1">скасуйте запис</a>.' % cancel_url,
        ],
    )
    return send(b.get("email"), subject, text, html)


def booking_confirmed(b, cancel_url):
    """To the client when the technician confirms."""
    when = slot_text(b["day"], b["hour"])
    subject = "Ви записані на тахосервіс — %s" % when
    text = (
        "Ваш запис підтверджено!\n\n"
        "Ви записані на тахосервіс на %s за адресою %s.\n"
        "Карта: %s\nТелефон: %s\n\n"
        "Скасувати запис: %s\n" % (when, ADDRESS, MAPS_URL, TACHO_PHONE, cancel_url)
    )
    html = _wrap_html(
        "Запис підтверджено 🎉",
        [
            "Ви записані на тахосервіс на <strong>%s</strong>" % when,
            "за адресою <strong>%s</strong>." % ADDRESS,
            "Якщо плани зміняться — <a href=\"%s\" style=\"color:#1b5fd1\">скасуйте запис</a> або зателефонуйте."
            % cancel_url,
        ],
        button=("📍 Показати на карті", MAPS_URL),
    )
    return send(b.get("email"), subject, text, html)


def booking_cancelled(b, by_client, reason=""):
    """To the client when a booking is cancelled (by admin or via their link).
    `reason` — optional admin-entered explanation included in the email."""
    import html as _html

    when = slot_text(b["day"], b["hour"])
    subject = "Запис на тахосервіс скасовано — %s" % when
    intro = "Ви скасували запис." if by_client else "На жаль, ваш запис скасовано майстром."
    reason_text = "\nПричина: %s\n" % reason if reason else ""
    text = (
        "%s\n%s\nЗапис на %s скасовано, година знову вільна.\n"
        "Щоб обрати інший час: https://minitrans.uz.ua/booking.html\nТелефон: %s\n"
        % (intro, reason_text, when, TACHO_PHONE)
    )
    lines = [intro, "Запис на <strong>%s</strong> скасовано." % when]
    if reason:
        lines.append("<strong>Причина:</strong> %s" % _html.escape(reason))
    lines.append(
        'Ви можете <a href="https://minitrans.uz.ua/booking.html" style="color:#1b5fd1">обрати інший час</a> '
        "або зателефонувати нам."
    )
    html = _wrap_html("Запис скасовано", lines)
    return send(b.get("email"), subject, text, html)


def notify_company(b, event):
    """To the company mailbox. event: 'new' | 'client_cancelled'."""
    import html as _html

    b = dict(b, **{k: _html.escape(str(b.get(k) or "")) for k in ("company", "phone", "email", "comment")})
    when = slot_text(b["day"], b["hour"])
    if event == "new":
        subject = "🆕 Новий запис на тахосервіс: %s — %s" % (when, b["company"])
        head = "До вас записались на тахосервіс"
        tail = 'Підтвердіть запис в <a href="https://minitrans.uz.ua/admin" style="color:#1b5fd1">адмінці</a>.'
        tail_text = "Підтвердіть запис в адмінці: https://minitrans.uz.ua/admin"
    else:
        subject = "❌ Клієнт скасував запис: %s — %s" % (when, b["company"])
        head = "Клієнт скасував запис на тахосервіс"
        tail = "Година знову вільна для запису."
        tail_text = tail
    details = [
        "<strong>Час:</strong> %s" % when,
        "<strong>Фірма / ім’я:</strong> %s" % b["company"],
        "<strong>Телефон:</strong> %s" % b["phone"],
    ]
    details_text = "Час: %s\nФірма: %s\nТелефон: %s\n" % (when, b["company"], b["phone"])
    if b.get("email"):
        details.append("<strong>Пошта:</strong> %s" % b["email"])
        details_text += "Пошта: %s\n" % b["email"]
    if b.get("comment"):
        details.append("<strong>Коментар:</strong> %s" % b["comment"])
        details_text += "Коментар: %s\n" % b["comment"]
    text = "%s\n\n%s\n%s" % (head, details_text, tail_text)
    html = _wrap_html(head, details + [tail])
    return send(NOTIFY_EMAIL, subject, text, html)
