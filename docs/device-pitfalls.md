# Device pitfalls & hard-won findings

Platform truths discovered while building this firmware — read before touching
fonts, input, drawing or the installer. Each of these cost real debugging time.
(Seat-specific notes — credential paths, `sg dialout`, sudo — live in the dev
seat's session memory, not here.)

## Fonts (the big one)

- **Pixel fonts only render correctly at grid-exact sizes.** The `.af` renderer
  scales glyph outlines by `size / 128`. Unless the font was quantized so one
  design pixel is an integer number of `.af` units AND the draw size is
  `128 * px / (units * native_px)`, strokes land at fractional positions and
  1px strokes drop columns unpredictably (letters missing vertical lines —
  diagonals like V/Y/M/N break first, because each staircase step has its own
  fractional phase, so no global offset can fix it; we tried). The ONLY correct
  fix is at conversion time: `tools/build-fonts.py` + the patched afinate
  (`tools/alright-fonts-local.patch`) + `firmware/font_metrics.py` +
  `design_fonts.effective_text_size()`. Never draw text at a raw px size, and
  never use sizes that are not native or an integer multiple.
- A 0.25px draw bias guards float-epsilon edge-on-boundary flips (advances like
  7.999998). Don't remove it.
- **Per-glyph drawing, not whole strings**: the engine places every glyph at an
  integer pixel column with the font's true per-character advance (these fonts
  are NOT strictly monospace: `i`/`.`/space are narrower; lowercase `i` is
  entirely missing from the MT Pixel fonts — the UI is all-caps, fine).
- Glyphs beyond basic latin must be added to the corpus in
  `tools/build-fonts.py` (`·` `•` `°` `×` are there today). afinate routes
  codepoints ≥ its icon boundary down a different path that mangles them —
  patched to 0xE000 (PUA); the bullet U+2022 hit this.
- **Never read binary files through the `mpremote mount` bridge** — it crashes
  the host-side server mid-session. Fonts load from device flash by absolute
  path only (`design_fonts._FONT_DIRECTORIES`); the dev loop copies them to
  `/fonts/` once.
- **The installed app's fonts SHADOW `/fonts/`** (`_FONT_DIRECTORIES` checks
  `/system/apps/ccstats/fonts/` first). After rebuilding a font, `cp` to
  `/fonts/` is NOT enough — REINSTALL the app, or every run (mounted dev runs
  included) keeps rendering the stale build. This burned an hour chasing a
  "fixed" font that measured old values.
- **The device's `.af` parser reads glyph ADVANCES as signed int8.** afinate
  packs them unsigned and raises no error, so an advance over 127 units wraps
  NEGATIVE on the badge: the cursor steps backwards and the next glyph
  overdraws the wide one (deer_diary 'W', advance 154 → -102, rendered as an
  unidentifiable merged symbol). `tools/build-fonts.py` now sizes the
  quantization grid by the widest corpus ADVANCE as well as the outline
  extents — keep it that way when adding fonts.

## Input & rendering

- `badge.pressed()` is a per-`poll()` edge. badgeware's stock `run()` polls
  once per frame, so any frame slower than a button press EATS presses. The
  firmware runs its own loop (navigation.start): poll every ~10ms, redraw only
  when navigation/data changed. Keep it that way; never tie input polling to
  draw cost.
- Full-screen vector redraws cost 120-210ms. Avoid per-pixel/per-tile shape
  spam: the checkerboard bar fill is ONE `brush.pattern` shape call (8-row
  bitmap, anchored to screen origin — compensate tile parity from the element
  origin), not hundreds of 2x2 rects.
- `color` objects have NO equality operator (`blank == blank` is False).
  Compare packed values via `.p` (pixel scans, cap-top probe).
- `badge.mode()` RECREATES the `screen` builtin — never hold a reference to
  `screen` across a mode switch. Boot is LORES 160x120; this firmware runs
  HIRES 320x240.
- Set `screen.antialias = image.OFF` for the pixel look; set brightness
  explicitly at boot (the panel inherits whatever the previous app left).
- **The contextual-B footer label is DUPLICATED — firmware and web have no
  shared source, so keep them in sync.** The firmware is authoritative: the
  real B behaviour and its label live in `B_HINTS`/`B_FLOWS` (+ per-screen
  special-cases) across `firmware/navigation.py`, `firmware/screens_options.py`
  and per-screen modules (e.g. `firmware/screens_trophies.py`). The web
  dashboard re-states just the *label* in `footerBLabel()` in
  `viewscreens/screens.js` — it's a static mirror and never runs the flow. When
  you add, rename or re-condition a B-contextual screen, update BOTH or the
  badge and the dashboard will disagree on what B does.

## Install & app lifecycle

- `/system` (FAT) is READ-ONLY at runtime, and every mpremote invocation
  soft-resets the board (remounting it ro) — installs must remount rw and
  write everything in ONE serial session. `tools/install-app.py` does this.
- The installer DERIVES its file list from `firmware/` and sweeps stale device
  files. It was once hand-maintained and shipped an app missing a module →
  ImportError at launch. Never go back to a hand-kept list.
- **"Runs from the mounted working tree" ≠ "runs as installed".** After every
  install, verify the real launch path:
  `mpremote soft-reset exec "import badgeware; launch('/system/apps/ccstats')"`
  (boot log over serial; a timeout means the loop is alive). `dev_smoke.py`
  renders every registry screen over mount and reports timings/errors.
- An interrupted launcher leaves a reset-on-HOME irq armed — `dev_run.py` /
  `dev_smoke.py` disarm it; the INSTALLED app must NOT (that irq is the
  exit-to-menu path).
- **A detached mount + a LAZY import = a hard-wedged badge.** Mounted dev
  runs keep running after the host detaches — but anything imported LATER
  (avatar_frames.sprite() lazy-loads avatar_sprite_<name>.py on first use)
  resolves against the dead `/remote` mount and blocks inside the VFS driver
  forever; the mount protocol shares the serial channel, so the REPL is
  unreachable too ("could not enter raw repl") and only the physical RESET
  button recovers. Demos that switch sprites must PRE-IMPORT every sprite
  they will visit while the host is still attached, or the host must stay
  attached (run mpremote in the background) for the demo's lifetime.
- Cold boots (PWRON: power-on/RESET button) auto-launch this app via the
  patched menu (`tools/enable-autoboot.py`); HOME/watchdog resets show the
  menu. Re-run the tool after a Pimoroni firmware update.
- The pre-commit leak scan prints harmless "ignored null byte" warnings when
  binary fonts are staged.

## Images & the launcher

- **`image.load()` decodes to 32-bit RGBA**: a full 320x240 PNG occupies
  300 KB of PSRAM regardless of file size, and ~7.2 MB of images is the
  practical allocation ceiling — a 36-frame full-screen animation set does
  NOT fit (MemoryError). Crop to the changing region instead (the splash hue
  frames: 260x103 ≈ 100 KB each). Decode costs ~147 ms full-screen / ~40 ms
  for a quarter-area crop; blit + display.update is ~30 ms, so ~30 fps is
  the from-RAM animation ceiling.
- **`screen.blit` wants `vec2`/`rect` args on this build** —
  `blit(sprite, x, y)` from the badgeware docs' examples raises
  "invalid parameter"; use `screen.blit(sprite, vec2(x, y))`.
- **MSC disk mode exposes ONLY the /system FAT** — the littlefs root
  (`/secrets.py` with the stats token, `/state/`) is invisible to a PC.
  Config that users edit in disk mode must live on /system: that is why
  WiFi networks are `/system/wifi.txt`. Beware the TWO `secrets.py` files:
  `/system/secrets.py` is the badgeware-STOCK config (WIFI_SSID/
  WIFI_PASSWORD/REGION/TIMEZONE — disk-mode editable, used by Pimoroni's
  apps and our last-resort WiFi fallback); `/secrets.py` on littlefs is the
  ccstats one (token etc., serial-only). `import secrets` resolves to the
  littlefs one ("/" precedes the app dir on sys.path).
  Read-only-at-runtime /system is fine for boot-read config.
- **The stock menu title-cases app directory names** ("ccstats" →
  "Ccstats") at scan time; fix the scanned entry's `.name` in the menu
  patch (tools/enable-autoboot.py does). The stock menu file also ships
  with CRLF line endings — normalize before any string matching against
  it, or patch-marker searches silently fail.
- **Menu-patch code runs in the menu's `__init__.py` scope** — `app.py`
  module globals (`bold`/`faded` tile colours, ...) are NOT visible as
  bare names there; reach them via `import app` (already in sys.modules).
  And ALWAYS runtime-verify a menu patch with
  `soft-reset exec "import badgeware\nlaunch('/system/apps/menu')"`
  (tracebacks come back over serial) — a compile check of the patched
  source missed a NameError that crashed the badge on HOME.

## Network

- TLS is verified (pinned ISRG roots, `http_client.py`) and fail-closed; the
  bundled `requests` is NOT (no verification, no context hook) — don't use it.
- A TLS handshake costs ~1.8 s on the badge, but a GET on an ESTABLISHED
  connection is 40-155 ms (small feeds) / ~280 ms (claude-stats.json) —
  `http_client.PersistentConnection` keeps one keep-alive socket and every
  poll rides it. nginx idle-closes after ~65 s and frames static files with
  Content-Length (no chunked), so HTTP/1.1 reuse is simple; a stale socket
  shows up as an OSError on the next request and is retried ONCE on a fresh
  connection (errors on a fresh connection propagate — the network is really
  down).
- **There is no way to fetch off the input loop on this stack** (verified
  2026-06-12): the badgeware 1.27 build has NO `_thread`, and MicroPython's
  ssl-over-asyncio streams BLOCK the scheduler during TLS work — a 10 ms
  ticker task got 48 beats during 6 s of async handshake+GET, so asyncio
  buys nothing. The working design is synchronous: warm GETs are shorter
  than a button press and run behind a tiny input-quiet gap; the ~1.8 s
  reconnect handshake waits for a long quiet window
  (`navigation.refresh_feeds_if_due`). Route ALL fetching through
  `feeds.FeedScheduler` — it also dedupes byte-identical responses (no
  parse, no redraw) and backs off 5→60 s after errors so a dead network
  is not hammered with handshake attempts.
