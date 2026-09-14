#!/bin/sh
# Runs every fixture plan twice through the CLI and requires byte-identical outputs.
set -eu
BIN="$1"
FIXTURES="$2"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
status=0
for plan in "$FIXTURES"/*.plan.json; do
  name="$(basename "$plan" .plan.json)"
  mkdir -p "$WORK/$name/a" "$WORK/$name/b"
  "$BIN" exec "$plan" "$WORK/$name/a" > "$WORK/$name/a.json"
  "$BIN" exec "$plan" "$WORK/$name/b" > "$WORK/$name/b.json"
  if ! cmp -s "$WORK/$name/a.json" "$WORK/$name/b.json"; then
    echo "FAIL: result JSON differs between runs for $name"; status=1
  fi
  for f in "$WORK/$name/a"/*; do
    if ! cmp -s "$f" "$WORK/$name/b/$(basename "$f")"; then
      echo "FAIL: $(basename "$f") differs between runs for $name"; status=1
    fi
  done
  grep -q '"ok":true' "$WORK/$name/a.json" || { echo "FAIL: $name did not succeed"; status=1; }
  echo "$name: $(ls "$WORK/$name/a" | tr '\n' ' ')"
done
exit $status
