#!/usr/bin/env bash
# amazon-pull-report — one-command bootstrap (macOS / Linux)
#
# Installs uv (the modern Python tool) if not present, then triggers
# auto-install of Python 3.9+ and the `requests` dependency by running --list.
set -euo pipefail

cd "$(dirname "$0")"

echo "amazon-pull-report setup"
echo "========================"
echo

# 1. uv
if command -v uv >/dev/null 2>&1; then
  echo "✓ uv already installed ($(uv --version))"
else
  echo "Installing uv (a tiny tool that manages Python for you)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # uv installs to ~/.local/bin or ~/.cargo/bin depending on platform.
  # Make sure it's on PATH for the rest of this session.
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  if ! command -v uv >/dev/null 2>&1; then
    echo
    echo "uv installed but not yet on your PATH."
    echo "Open a new terminal window and re-run: bash setup.sh"
    exit 1
  fi
  echo "✓ uv installed ($(uv --version))"
fi

echo
echo "Installing Python and dependencies (one-time, ~30 seconds)…"
uv run bin/run.py --list >/dev/null
echo "✓ Python and 'requests' ready"

echo
echo "Setup complete!"
echo

# Find an existing .env in any of the locations the skill checks at runtime
# (project root, ~/.config/amazon-pull-report, skill folder). If none exist,
# drop a template at the project root so the seller has a clear starting point.
PROJECT_ROOT=$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null || true)
if [ -z "$PROJECT_ROOT" ]; then
  # Not a git repo — fall back to the directory the user invoked setup from.
  PROJECT_ROOT=$(cd "$(dirname "$0")/../../.." 2>/dev/null && pwd || pwd)
fi
USER_ENV="$HOME/.config/amazon-pull-report/.env"
SKILL_ENV="$(dirname "$0")/.env"

EXISTING=""
for cand in "$PROJECT_ROOT/.env" "$USER_ENV" "$SKILL_ENV"; do
  if [ -f "$cand" ]; then
    EXISTING="$cand"
    break
  fi
done

if [ -n "$EXISTING" ]; then
  echo "Found existing credentials at: $EXISTING"
  echo "Next step: pull your first report:  uv run bin/run.py --report orders-by-order-date --days 7"
else
  TARGET="$PROJECT_ROOT/.env"
  cp "$(dirname "$0")/.env.example" "$TARGET"
  chmod 600 "$TARGET" 2>/dev/null || true
  echo "Created credentials template at:  $TARGET"
  echo
  echo "Next steps:"
  echo "  1. Open $TARGET and paste in your four LWA / SP-API values."
  echo "     See SETUP.md for how to get them from Seller Central."
  echo "  2. Add '.env' to your project's .gitignore if it isn't already."
  echo "  3. Pull your first report:        uv run bin/run.py --report orders-by-order-date --days 7"
fi
