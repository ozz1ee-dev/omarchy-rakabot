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
| `Widget.qml` | the bar entry and the panel; **also where settings live** |
| `Avatar.qml` | one bot, drawn: shape, colour, eyes, expression, flourishes |

Settings only reach a bar widget, never a service, so everything configurable is
read in `Widget.qml` from the plugin's `shell.json` entry: `barMetric`, `ordering`,
`groupBySection`, `maxBarAvatars`.

## Running and testing

```bash
python3 -B -m unittest discover -s tests -v   # watcher + setup, against a fake server
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
