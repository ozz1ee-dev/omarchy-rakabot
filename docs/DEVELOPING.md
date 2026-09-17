# Working on Rakabot

> Not called `AGENTS.md`, and not at the repository root, on purpose. Omarchy
> installs a plugin's whole tree into `~/.config/omarchy/plugins/`, so a root
> agent-instruction file would become ambient context for any coding agent the
> *installing user* happens to run - instructions they never chose to load.

Your Rakazo roster in the Omarchy bar. It reads the server's own RPC API with a
session token that belongs to the person running the bar, and renders each bot as
itself - the shape and colour Rakazo gives it, or the picture you set - wearing a
face for what it wants from you.

**It only ever reads.** The four procedures it calls (`health`, `bots/list`,
`botSections/list`, `groups/list`) are reads; nothing is sent to a bot, no run is
started or stopped, no message is marked read. If a change here would write to the
server, it is the wrong change.

## Layout

| | | |
| --- | --- | --- |
| `bin/rakabot-watch` | polls the server and streams JSON lines on stdout |
| `bin/rakabot-setup` | writes the server address and mints a session token |
| `bin/rakabot-open` | opens Rakazo the way this machine already uses it |
| `Widget.qml` | the bar entry and the panel; **also where settings live** |
| `Avatar.qml` | one bot, drawn: shape, colour, eyes, expression, flourishes |

Settings only reach a bar widget, never a service, so everything configurable is
read in `Widget.qml` from the plugin's `shell.json` entry: `barMetric`, `ordering`,
`groupBySection`, `maxBarAvatars`, `openWith`.

## Running and testing

```bash
python3 -B -m unittest discover -s tests -v   # watcher + setup, against a fake server
python3 scripts/check-persona-parity.py       # our avatar hash against Rakazo's own code
qmllint Widget.qml Avatar.qml                 # CHECK THE EXIT CODE
python3 scripts/check-manifest.py .
omarchy plugin validate .                     # what the marketplace runs
omarchy restart shell                         # reload (never omarchy-refresh-shell)
bin/rakabot-watch --interval 2                # the raw stream, one JSON line per change
bin/rakabot-setup --url https://rakazo.example --check   # prove a server answers, write nothing
omarchy-shell ozz1ee.rakabot demo             # staged roster, again to go back
```

`demo` is the way to see states you cannot summon: fourteen invented bots across
two sections, one of them waiting. It is held in memory, which is why it is an IPC
verb rather than a setting - writing the bar entry reloads the widget and would
throw the roster away. `scrub` redacts names and messages for a screen share;
`group` / `order` cycle the ordering.

**Hot reload does not recreate `Variants` windows.** Editing `Widget.qml` or
`Avatar.qml` means a full restart, or you are looking at the old surface and
chasing a bug that is not there.

## Things that cost a day to learn

**A panel is narrower than it looks**

- The card is `Style.space(420)` at most, and the padding
  (`Style.spacing.popupPadding` twice) plus the column insets leave roughly 384 px
  for text. The key hint at the foot of the panel was one fixed 69-character
  string: at the caption size that is ~455 px, so it ran past the card edge.
  Measure with `TextMetrics` against the width the text actually has and step down
  through shorter wordings before eliding - font size is a theme token, so a
  wording that fits today can overflow tomorrow.
- Anything that has to fit is `width: parent.width` plus `elide`, not a fixed
  string relying on today's font.

**Opening Rakazo is a cascade, not a URL**

- An Omarchy web app reports a window class built from the address it was made for
  (`chrome-<host>__<path>-Default` for a Chrome app window), the Rakazo desktop app
  reports `rakazo`, and a plain browser tab carries the host in its title. Matching
  has to be word-bounded (`\brakazo\b` must not match `notrakazo.example`) and
  class-first, or a stray tab hijacks the click.
- An installed web app is a desktop entry in `~/.local/share/applications` that
  opens the address as an app window. Two forms are in the wild: Omarchy's
  `Install > Web App` writes `Exec=omarchy-launch-webapp <url>` (named after the
  site, `Rakazo.desktop`), and a browser shortcut writes
  `Exec=chrome --app=<url>` with `StartupWMClass=chrome-<host>__-Default`. Match
  both on the address, never on the entry's name. Omarchy's own
  `omarchy-launch-or-focus-webapp` is the reference for the focus-then-launch
  order, but it always opens an app window - the browser is *our* last resort, so
  `bin/rakabot-open` decides and `--prefer` forces a branch.
- Every external command in that path (`hyprctl`, `gtk-launch`, `xdg-open`,
  `omarchy-launch-webapp`, `wtype`) is asserted in `tests/test_open.py` through
  PATH shims, so the cascade is testable without a live session.
- **Keep that harness hermetic: `PATH` holds the shim directory and nothing else.**
  With the real `/usr/bin` behind the shims, a test for "the tool is missing"
  quietly reaches the real binary - and a `wtype` fall-through types into whatever
  window the developer has focused. The shims themselves use bash builtins only
  (`${0##*/}`, `$(<file)`) so they do not need `/usr/bin` either.

**Switching the open window to a bot**

- Rakazo has real deep links - `/app/<botId>`, `/app/g/<groupId>`, and `?m=` /
  `?routine=` for a message or a routine - so a bot can be addressed, but a
  *running* app window cannot be navigated from outside: Chrome opens a new app
  window per `--app=<url>` (reproduced: relaunching the same address made a second
  window), and Ctrl+L does not raise an omnibox in app mode.
- The way in is the app's own command palette: `Ctrl+K`, type the bot's name, and
  `Enter` selects the highlighted result. Verified end to end by the roster's own
  unread flag going from 1 to 0, which is the app marking the thread it opened.
- Two guards, both tested: `Escape` first (a palette the user left open would be
  closed by our Ctrl+K and the name would then land somewhere else), and nothing is
  typed at all unless `hyprctl activewindow` says the Rakazo window we are about to
  drive is the focused one. Without that check a stray `Enter` could send a message.
- The name has to be unique enough to rank first in the palette - names are not ids.

**Rakazo's RPC surface is not a contract**

- The API is oRPC over `POST /rpc/<procedure>` with `{"json": {...}}` envelopes,
  and the reply is `{"json": ...}`. A failure inside a procedure can still come
  back as HTTP 200 with an error envelope, so both shapes are checked.
- The bearer token is a Better Auth session: `Authorization: Bearer <token>` is
  translated into the session cookie server-side. A token minted through
  `/api/auth/sign-in/email` dies when that session is revoked, and the watcher
  says so (`the session token was rejected (401)`) rather than going quiet.
- Every field is read defensively and an unfamiliar shape degrades to an empty
  roster. Rakazo is in beta and ships `edge` images; when a payload moves, the
  file to fix is `bin/rakabot-watch`.

**The avatar encoding**

- `bot.color` is one of `#RRGGBB`, `#RRGGBB::shape_N`, or a `data:image/...` URL
  once someone uploads a picture. `shape_N` indexes the app's shipped shape list
  (`hex, wedge, squircle, tablet, pebble, blob, teardrop, cloud`); a bare hex gets
  a shape from a hash of the bot's id instead. `bin/rakabot-watch` reimplements
  that hash (`shipped_hash` / `shipped_random`) and `tests/test_watch.py` pins it
  against values produced by the app's own TypeScript.
- Uploaded pictures are written into
  `~/.local/state/omarchy/rakabot/avatars`, named by the SHA-256 of the data URL,
  created 0600 inside a 0700 directory, with an unpredictable temporary name. A
  symlinked cache directory or entry, a FIFO, or an oversized payload is refused
  and the bot falls back to its shape. Nothing prunes that directory: a picture
  that changes leaves the old one behind, and deleting the directory is safe.
- Pictures are never fetched over the network: only `data:` URLs are decoded, so a
  roster cannot make the bar call out to a third party.

**Watching a server, not a file**

- The watcher polls (default 5s, `--interval` to change) and emits only when the
  signature of what the widget draws changes, plus a one-minute heartbeat so a
  server that stopped answering is noticed without any traffic.
- `app.running` means "the server answered", not "an application is open"; the
  mark dims when it is false, and `app.error` carries the reason into the panel's
  empty state.
- No roster cache is kept on disk. The one thing written locally is a decoded
  picture.
