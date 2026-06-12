# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Marketing site for **МПП Мінітранс** — a freight/logistics company in Uzhhorod (Закарпаття), Ukraine. Bilingual (Ukrainian default, English). Lives at `minitrans.uz.ua`, deployed on Vercel.

## Stack & workflow

Static site + a Python backend in `api/` (Vercel Python serverless functions) with **Postgres** storage. Hand-written HTML, one CSS file (`styles.css`), one vanilla-JS file (`script.js`). Only Python dependency: `pg8000` (`requirements.txt`, pure-python Postgres driver). `.venv/` holds pg8000 + Pillow for local work.

- **Develop:** `.venv/bin/python3 dev_server.py` (port 8080) — serves static files **and** `/api/*` using the same handler classes Vercel runs. Dev admin password: `minitrans`. Dev DB: local Homebrew Postgres, database `minitrans` (browse with pgAdmin; tables auto-create on first API call).
- **Deploy:** push to `origin` (`github.com/MatrixRosul/minitrans`); Vercel builds from the repo root. `/_vercel/insights/script.js` (Vercel Analytics) is included in every page `<head>`.

## Backend (`api/`) and admin

`admin.html` is a standalone admin panel (login → manage sales posts, tacho-service bookings — incl. a 14-day calendar with detail modal and direct admin booking of free slots — and job applications with downloadable CV files). It is served at the clean URL `/admin` (vercel.json rewrite in prod; dev_server.py falls back to `<path>.html` for extensionless paths).

**Job applications** (`vacancies.html` form + `api/applications.py`/`api/appfile.py`): public POST with honeypot, 3-per-phone/24h cap, up to 3 files (PDF/DOC/DOCX/JPG/PNG, ≤3MB each) sent as base64 in JSON and stored as `bytea` (`application_files`); files are admin-only via `/api/appfile?id=`. Candidate gets an ack email; company gets a notification.

**Neon cold start**: the free-tier DB suspends after idle; `db._connect` retries 3× (timeout 10s) and the admin UI retries GET loads once after 2.5s — that's the fix for sporadic "Внутрішня помилка сервера" right after opening the admin. Endpoints (each exports a `handler(BaseHTTPRequestHandler)` class): `api/auth.py` (HMAC cookie session), `api/sales.py` (CRUD; GET is public and hides `hidden` posts for non-admins), `api/bookings.py` (tacho-service booking), `api/upload.py` + `api/img.py` (photos), `api/health.py` (setup status). Shared code sits in `api/_lib/` (underscore = not routed by Vercel; imported via a `sys.path` insert at the top of each endpoint).

**Booking model** (`booking.html` + `api/bookings.py`): slots Mon–Sat, start hours 09–17 (Kyiv time), 1 client/hour, 14-day horizon. Public GET returns slot statuses only (`free|pending|busy|past`), never client data; POST creates a `pending` booking (DB-level `UNIQUE(day, hour)` prevents double-booking → 409); admin PUT confirms (`confirmed`), DELETE rejects/cancels and frees the slot; `api/cancel.py` lets the client cancel via an HMAC-signed link from their email.

**Email** (`api/_lib/mail.py`): two transports, auto-selected — Resend HTTP API (`RESEND_API_KEY`, sends from `MAIL_FROM` default `booking@minitrans.uz.ua`, `REPLY_TO` default stominitrans@gmail.com) or Gmail SMTP (SSL :465, `GMAIL_USER`+`GMAIL_APP_PASSWORD`; requires 2FA + app password; port 25 is blocked on Vercel, 465 is not). Sends are synchronous (must finish before the response on Vercel) and never raise. `NOTIFY_EMAIL` (default = GMAIL_USER) receives company notifications. Without either transport sends are skipped and logged — booking flow still works.

**Security/abuse notes**: signing key = `ADMIN_SECRET` env (recommended) or PBKDF2-stretched `ADMIN_PASSWORD`; on Vercel with neither set auth is impossible by design. Public booking POST has a honeypot field (`website`), per-contact cap (3 active) and global pending cap (40). API error responses are generic; details go to function logs. The home page has a mini slot calendar (`initTachoWidget` in `script.js`, `#tacho-widget` in `index.html`) whose free slots deep-link to `booking.html?date=&hour=` for pre-selection.

Database resolution (`api/_lib/db.py`): `DATABASE_URL`/`POSTGRES_URL` env if set (production: Neon via Vercel Marketplace); local fallback `postgres://<user>@127.0.0.1:5432/minitrans` in dev; on Vercel without a DB endpoints return 503 and the public site falls back to its static content. Tables: `sales_posts`, `photos` (photos stored as `bytea`, served via `/api/img?id=`; Vercel Blob is used instead when `BLOB_READ_WRITE_TOKEN` is set). **Production needs env vars on Vercel: `ADMIN_PASSWORD` (required) and a Postgres database (required for posts).**

`sales.html` renders posts from `GET /api/sales` (see `initSalesPage` in `script.js`); if the API is absent/unconfigured, the static example cards remain — keep that fallback intact.

## Architecture

Five standalone HTML pages, all sharing `styles.css` and `script.js`:

- `index.html` — main landing page (hero, about, services, fleet, infrastructure, advantages, contacts).
- `vacancies.html` — careers page with an application `<form>`.
- `sales.html` — equipment-sales catalogue; cards render from `GET /api/sales` (managed via `admin.html`), with static example cards as fallback when the backend is unavailable.
- `booking.html` — online tacho-service booking (slot grid + request form, see Booking model below).
- `privacy.html`, `terms.html` — legal pages.

Every page hardcodes the same header/footer markup; there is no templating/includes, so **navigation, footer, and shared chrome must be edited in each HTML file**.

### Internationalization (the central mechanism)

All user-facing text is keyed and translated at runtime by `script.js`. The `translations` object (top of `script.js`, ~460 entries) holds parallel `uk` and `en` maps. Markup carries the key via data attributes; `setLanguage(lang)` walks the DOM and fills text/attributes:

- `data-i18n` → `textContent`
- `data-i18n-html` → `innerHTML`
- `data-i18n-placeholder` → input `placeholder`
- `data-i18n-alt` → `<img alt>`
- `data-i18n-aria` → `aria-label`

Language is persisted in `localStorage` under `siteLang` and toggled by `[data-lang]` buttons (UA/EN). The active button gets `.is-active`.

**When adding or changing any visible text:** add the matching key to **both** `uk` and `en` in `translations`, and put the correct `data-i18n*` attribute on the element. Don't hardcode strings in HTML expecting them to display — `setLanguage` overwrites the default markup text on load.

### script.js init functions

Run at the bottom of the file on load: `initLanguage`, `initNavToggle` (mobile menu + backdrop + focus trap + Escape), `initReveal` (`IntersectionObserver` adds `.is-visible` to `[data-reveal]` elements; falls back to showing all if unsupported), `setYear` (fills `[data-year]`).

## SEO / static config

`sitemap.xml` and `robots.txt` exist at root and reference the four public pages. **When adding or removing a page, update `sitemap.xml`** (and the shared nav/footer links in every HTML file). `index.html` `<head>` carries the SEO `<title>`/`description`/`keywords` and social meta — keep those in sync with content changes.

## Conventions

- Content language is Ukrainian; the company name renders as "МПП Мінітранс". Match the existing typographic apostrophe (`’`) used throughout the strings.
- Images live in `assets/images/`. The loose `photo_*.jpeg` and `.pdf` files at repo root are source/reference material, not used by the site.
