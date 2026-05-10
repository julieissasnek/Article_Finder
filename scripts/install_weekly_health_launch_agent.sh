#!/bin/zsh
set -euo pipefail

ROOT="/Users/davidusa/REPOS/Article_Finder_v3_2_3"
PLIST="$ROOT/ops/launchd/com.articlefinder.weekly_system_health.plist"
TARGET="$HOME/Library/LaunchAgents/com.articlefinder.weekly_system_health.plist"

mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST" "$TARGET"
launchctl unload "$TARGET" >/dev/null 2>&1 || true
launchctl load "$TARGET"
echo "Installed com.articlefinder.weekly_system_health"
