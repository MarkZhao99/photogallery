#!/bin/sh
set -eu

git rev-parse --show-toplevel >/dev/null 2>&1

if [ ! -f ".githooks/pre-push" ]; then
  echo "Missing .githooks/pre-push in this repository." >&2
  exit 1
fi

chmod 755 ".githooks/pre-push"
git config core.hooksPath .githooks
echo "Installed repository Git hooks: .githooks"
