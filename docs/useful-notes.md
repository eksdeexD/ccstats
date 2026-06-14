# Useful notes for hacking on this project

Practical knowledge for anyone working on the firmware or the web dashboard —
the things that aren't obvious from the code but make development a lot faster.
Platform gotchas that cost real debugging time live separately in
[`device-pitfalls.md`](device-pitfalls.md); read that before touching fonts,
input, drawing or the installer.

## The firmware ↔ viewscreens relationship

`viewscreens/screens.js` — drawing through `viewscreens/pico.js`, a
PicoGraphics-shaped ~10-primitive shim (rect / border / hline / pixel / text /
…) — **is the canonical screen design.** The MicroPython firmware reimplements
that same shim on-device and ports each screen ~1:1, at **absolute integer
pixel coordinates**. So the web dashboard isn't just a viewer; it's the spec.

When you change a screen, change it in **both** places and keep them in
agreement. The web side is a static mirror — it renders the layout (and the
footer A/C arrows + contextual-B label) but never runs the live avatar
animation, the speech bubble, or any button press. Those are firmware-only.

## Verifying a viewscreens change with headless Chromium

You can check the dashboard pixel-for-pixel without the badge. Playwright (with
Chromium) drives a real browser against a locally served copy of the repo:

1. Serve the repo: `python3 -m http.server 8137`
2. Load the **full rack** at `http://localhost:8137/viewscreens/index.html`, or
   render **one screen full-size** with
   `http://localhost:8137/viewscreens/index.html?only=<slug>` — the slugs are
   the `SCREENS` keys in `screens.js` (e.g. `projects`, `tokens`).
3. Set the palette with `localStorage['viewscreens_theme']` before load.
4. Assert colours/layout by reading canvas pixels with Playwright's
   `page.evaluate` (grab the `<canvas>` 2D context and sample pixels).

This is how screen ports and theme changes get verified objectively — much
faster and more reliable than eyeballing.

**Caveat — local serving hides bare-path bugs.** Loading the page as
`.../viewscreens/index.html` (a real filename) is NOT how the deployed site is
reached. nginx serves the dashboard at the *bare* path `/viewscreens` (an
exact-match `alias` straight to `index.html`, no trailing slash — see
`server/nginx/stats-site.conf.template`). A **relative** `url()` / `src` /
`fetch` therefore resolves against `/` on the server but against `/viewscreens/`
locally, so an asset referenced relatively will load in headless Chromium yet
404 in production. To reproduce the real behaviour, hit the bare path through a
server that mimics the alias, or just follow the rule below.

## Asset paths in viewscreens must be absolute

**Always reference dashboard assets with an absolute, `/viewscreens/`-rooted
path** — never relative. The whole app already assumes this mount point
(`FONT_BASE` in `index.html` is `'/viewscreens/fonts/'`), and nginx serves the
HTML at the bare `/viewscreens` path, so a relative path resolves against `/`
and 404s.

This bit us once: the built-in fonts (Press Start 2P, Silkscreen) were moved
into `viewscreens/fonts/builtin/` during the single-repo migration and pointed
at with a *relative* `url('fonts/builtin/…')`. It rendered fine locally (page
loaded as `…/index.html`) but 404'd on the server (page is `/viewscreens`), so
every `silk`-role element — stat cards, calendar day numbers, tool counts,
captions, section labels — silently fell back to the browser's `monospace`. Fix
was `url('/viewscreens/fonts/builtin/…')`. The `location ^~ /viewscreens/fonts/`
block serves anything (incl. subdirs like `builtin/`) under that prefix.

## The badge dev loop

After MicroPython is flashed once (see the README), everything is over USB
serial with `mpremote` (you must be in the `dialout` group):

- **Fast iteration:** `mpremote mount firmware/` runs the working tree directly
  off the host with no copy step — edit, re-run, repeat.
- **Persistent install:** `python tools/install-app.py` writes the app to the
  device, then `mpremote reset` to launch it. Use this to test the *real*
  installed launch path (it differs from a mounted run — see device-pitfalls).
- Tracebacks and `print()` output come back over the serial connection — read
  them; that's your debugging channel.

## Working on the badge remotely

The whole loop runs over serial, so badge development doesn't need you (or
Claude) physically at the device — flash, install, reset, and read logs all
happen over USB. The only things that genuinely need hands on the hardware are
the physical actions: unplugging USB to test battery mode, tapping the RESET
button, and reading what's actually on the LCD. The on-device display can't be
observed over serial, so confirm visual changes by describing the expected
output, or verify the equivalent screen in `/viewscreens` with headless
Chromium (above).
