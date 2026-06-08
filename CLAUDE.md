# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Marketing site for **МПП Мінітранс** — a freight/logistics company in Uzhhorod (Закарпаття), Ukraine. Bilingual (Ukrainian default, English). Lives at `minitrans.uz.ua`, deployed on Vercel.

## Stack & workflow

Plain static site — **no build step, no package manager, no tests, no framework**. Just hand-written HTML, one CSS file (`styles.css`), and one vanilla-JS file (`script.js`). There is a `.venv/` in the repo but it is unrelated to serving the site.

- **Develop:** open `index.html` directly, or serve the folder, e.g. `python3 -m http.server 8000` then visit `http://localhost:8000`. Use a server (not `file://`) so relative paths and `localStorage` behave normally.
- **Deploy:** push to `origin` (`github.com/MatrixRosul/minitrans`); Vercel builds from the repo root. `/_vercel/insights/script.js` (Vercel Analytics) is included in every page `<head>`.

## Architecture

Four standalone HTML pages, all sharing `styles.css` and `script.js`:

- `index.html` — main landing page (hero, about, services, fleet, infrastructure, advantages, contacts).
- `vacancies.html` — careers page with an application `<form>`.
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
