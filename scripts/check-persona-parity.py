#!/usr/bin/env python3
"""Check that our avatar hash draws the same bot Rakazo's own code does.

A bot whose colour carries no shape gets one from a hash of its id, and the same
for its palette entry. If the two implementations drift, the bar shows a bot as
something the app never would - a bug nobody would report, because both look
fine on their own.

The JavaScript below is copied from Rakazo's packages/ui-web/src/bot-avatar.tsx
(shippedHash, shippedRandom, resolvePersonaShape, resolvePersonaColorDef). When
Rakazo changes those, copy them again and see this test fail or pass honestly.

    python3 scripts/check-persona-parity.py [--require-node]

Exits 0 when the two agree, 1 when they do not (or when node is missing and
--require-node was given, which is what CI does).
"""
import json
import importlib.machinery
import importlib.util
import os
import shutil
import subprocess
import sys

WATCHER = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "bin", "rakabot-watch")

IDENTITIES = [
    "bot_cabc123",
    "clx0a1b2c3d4e5f6",
    "77a1f0e2-0d5f-4a01-9b6c-111111111111",
    "Chief of Staff",
    "a",
    "zzzzzzzzzzzzzzzzzzzzzzzzzzzz",
    "8f14e45fceea167a5a36dedd4bea2543",
    "Release Notes",
    "0",
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
]

JS = r"""
const GROK_COLOR_LIST = [
  { id: "white" }, { id: "violet" }, { id: "green" }, { id: "orange" }, { id: "cyan" },
  { id: "blue" }, { id: "yellow" }, { id: "brown" }, { id: "red" }, { id: "magenta" }, { id: "gray" },
];
const SHIPPED_SHAPE_KEYS = ["hex", "wedge", "squircle", "tablet", "pebble", "blob", "teardrop", "cloud"];
function shippedHash(value) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash = Math.imul(hash ^ value.charCodeAt(index), 16777619);
  }
  return hash >>> 0;
}
function shippedRandom(seed) {
  let value = seed >>> 0;
  return () => {
    value = (value + 1831565813) | 0;
    let next = Math.imul(value ^ (value >>> 15), 1 | value);
    next = (next + Math.imul(next ^ (next >>> 7), 61 | next)) ^ next;
    return ((next ^ (next >>> 14)) >>> 0) / 4294967296;
  };
}
function resolvePersonaShape(identity) {
  let hash = shippedHash(identity);
  hash = Math.imul(hash ^ (hash >>> 16), 73244475);
  hash = Math.imul(hash ^ (hash >>> 13), 3266489909);
  const index = ((hash ^ (hash >>> 16)) >>> 0) % SHIPPED_SHAPE_KEYS.length;
  return SHIPPED_SHAPE_KEYS[index] ?? "hex";
}
function resolvePersonaColor(identity) {
  const seed = (shippedHash(identity) ^ Math.imul(1, 2654435769)) >>> 0;
  const index = Math.floor(shippedRandom((seed ^ 2654435769) >>> 0)() * GROK_COLOR_LIST.length);
  return GROK_COLOR_LIST[index % GROK_COLOR_LIST.length].id;
}
const identities = JSON.parse(process.argv[2]);
console.log(JSON.stringify(identities.map((id) => [resolvePersonaShape(id), resolvePersonaColor(id)])));
"""


def load_watcher():
    loader = importlib.machinery.SourceFileLoader("rakabot_watch", WATCHER)
    spec = importlib.util.spec_from_loader("rakabot_watch", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def upstream():
    node = shutil.which("node")
    if not node:
        return None
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".persona-parity.tmp.mjs")
    with open(script, "w") as handle:
        handle.write(JS)
    try:
        result = subprocess.run([node, script, json.dumps(IDENTITIES)], capture_output=True, text=True,
                                timeout=60, check=False)
    finally:
        os.unlink(script)
    if result.returncode != 0:
        raise SystemExit("node failed: %s" % result.stderr.strip())
    return json.loads(result.stdout.strip().splitlines()[-1])


def main():
    require_node = "--require-node" in sys.argv[1:]
    expected = upstream()
    if expected is None:
        message = "node is not installed, so Rakazo's own implementation could not be run"
        if require_node:
            print("FAIL: %s" % message)
            return 1
        print("SKIP: %s" % message)
        return 0
    module = load_watcher()
    failures = 0
    for identity, (shape, colour) in zip(IDENTITIES, expected):
        mine = (module.persona_shape(identity), module.persona_color(identity))
        if mine != (shape, colour):
            failures += 1
            print("FAIL: %r -> app %s, rakabot %s" % (identity, (shape, colour), mine))
    if failures:
        print("%d of %d identities disagree with Rakazo" % (failures, len(IDENTITIES)))
        return 1
    print("OK: %d identities agree with Rakazo's own avatar hash" % len(IDENTITIES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
