# Changelog

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
