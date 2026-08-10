#!/usr/bin/env bash
# Run the example the way an adopter would: against a built wheel, installed
# into a clean virtual environment, with duly's source tree NOT on sys.path.
#
# This is the part that makes the example a *probe* rather than a demo. Every
# place the toolkit quietly assumes it is running inside its own repository —
# a path relative to a package file, a default that expects `rulepacks/` to
# exist — fails here and nowhere else. Passing tests in the repo prove
# nothing about it, because in the repo the assumption is always true.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "==> building the wheel"
rm -rf "$REPO/dist"
( cd "$REPO" && uv build --wheel --out-dir "$WORK/dist" >/dev/null )
WHEEL="$(ls "$WORK"/dist/duly-*.whl)"
echo "    $(basename "$WHEEL")"

echo "==> installing into a clean venv"
python3 -m venv "$WORK/venv"
# Plain, no extras. That is the second thing this script probes: an adopter who
# writes `pip install duly` and imports the kernel should not inherit an HTTP
# framework, an ASGI server or a PDF renderer. `run.py` below proves the
# install is *enough*; the assertion here proves it is not *more*.
"$WORK/venv/bin/pip" install --quiet --disable-pip-version-check "$WHEEL"

echo "==> asserting the bare install stays bare"
# Two: duly itself and PyYAML, which is the whole of `[project] dependencies`
# — a rule pack is YAML, so the document→receipt path needs a YAML parser and
# nothing else. pip itself does not appear in `pip freeze`.
#
# Everything the demo, the review API and the PDF report need is behind the
# `demo` and `report` extras, so this number moves only when someone adds a
# dependency to `[project]`. If that is deliberate, update the number *and*
# SECURITY.md's "Dependencies" section, which makes the claim this pins.
EXPECTED_PACKAGES=2
FROZEN="$("$WORK/venv/bin/pip" freeze)"
COUNT="$(printf '%s\n' "$FROZEN" | grep -c . || true)"
if [ "$COUNT" -ne "$EXPECTED_PACKAGES" ]; then
  echo
  echo "FAIL: a bare 'pip install duly' now brings $COUNT packages, expected $EXPECTED_PACKAGES." >&2
  printf '%s\n' "$FROZEN" | sed 's/^/    /' >&2
  echo "If a new core dependency is intentional, update EXPECTED_PACKAGES here" >&2
  echo "and the dependency claim in SECURITY.md." >&2
  exit 1
fi
printf '%s\n' "$FROZEN" | sed 's/^/    /'

echo "==> copying the example out of the repository"
# Copied to a temp directory so that even an accidental relative path back
# into the repo fails rather than silently resolving.
cp -R "$HERE" "$WORK/example"
rm -rf "$WORK/example/receipt.json"

echo "==> running from $WORK/example (repo not importable)"
cd "$WORK/example"
# PYTHONPATH is cleared and cwd is outside the repo: the only duly on the
# path is the installed wheel.
env -u PYTHONPATH "$WORK/venv/bin/python" run.py

echo
echo "==> comparing against the committed receipt"
# The committed receipt.json is a build artifact kept honest here: a wheel in
# a clean venv on another machine must reproduce it byte for byte. That is
# determinism across *environments*, which is a stronger claim than
# determinism across runs and the one an adopter actually depends on.
if ! diff -u "$HERE/receipt.json" "$WORK/example/receipt.json"; then
  echo
  echo "FAIL: the wheel produced a different receipt than the committed one." >&2
  echo "If this change is intentional, re-run 'python run.py' and commit receipt.json." >&2
  exit 1
fi
echo "    byte-identical"

echo
echo "OK — the example ran against an installed wheel with no repository present."
