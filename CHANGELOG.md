# Changelog

## 0.3.0

- Picking a bot now switches the open Rakazo window to that bot, not just raises
  it. Rakazo keeps the open bot in its address but a running app window cannot be
  navigated from outside, so the switch drives the app's own command palette
  (`Ctrl+K`, the bot's name, `Enter`) - verified by the roster's unread flag going
  from 1 to 0 as the app opened the thread. Nothing is typed unless the Rakazo
  window is verifiably focused, and a palette left open is dismissed first.
- New `selectBot` setting (default on) to keep the old raise-only behaviour.

## 0.2.1

- 0.2.0 only recognised launchers written as `Exec=chrome --app=<address>`, so a
  Rakazo web app installed through Omarchy (`Install > Web App`, which writes
  `Exec=omarchy-launch-webapp <address>`) was invisible to it and the browser was
  used instead. Both forms are matched now, plus a `StartupWMClass` that names the
  address for browser app installs. Entries are no longer matched on their name:
  a launcher that mentions Rakazo is not necessarily one that opens it.

## 0.2.0

- Picking a bot opens Rakazo where you already keep it: an open window first - an
  Omarchy web app (`omarchy webapp add`), the Rakazo desktop app, or a browser -
  then the installed web app launcher, then the browser. It used to always reach
  for the browser even with a Rakazo web app window sitting right there.
- New `openWith` setting (`auto`, `web-app`, `browser`) to force one of those.
- New `bin/rakabot-open` does the deciding, with the cascade covered by PATH-shim
  tests (`tests/test_open.py`).

## 0.1.3

- Each derived file now carries a notice of modification at the top, as section
  4(b) of the Apache licence requires, and NOTICE lists which files are derived
  and which are new. No behaviour change.

## 0.1.2

- The keyboard hint at the foot of the panel no longer runs past the card edge.
  It is measured with `TextMetrics` against the width it actually has and steps
  down through two shorter wordings before eliding, so it fits at every theme
  font size. omabot's single wording overflows at this panel width.

## 0.1.1

- The watcher re-reads its configuration on every pass. Running `rakabot-setup`
  after the bar is already up no longer needs a shell restart before the widget
  starts reading - it used to sit on "no server configured" until one.

## 0.1.0

- First release: your Rakazo roster in the Omarchy bar, read from the server's own
  RPC API with a session token.
- Bots and groups drawn with the shape and colour Rakazo gives them, or with an
  uploaded picture when there is one.
- Waiting, working and unread states; oldest wait first in the bar and the panel.
- Settings for what sits beside the mark, the panel order, section grouping and how
  many avatars the bar shows.
- `bin/rakabot-setup` writes the server address and mints a session token, with
  `--check` to prove a server answers and write nothing.
- Read-only by construction: four read procedures, no roster cache, no network
  calls except to your own server.
