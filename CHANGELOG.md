# Changelog

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
