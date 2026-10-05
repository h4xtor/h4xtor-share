#!/bin/bash
# Cloud sessions only: install playwright-cli (uses the preinstalled Chromium).
[ "$CLAUDE_CODE_REMOTE" = "true" ] || exit 0
command -v playwright-cli >/dev/null || PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm i -g @playwright/cli >/dev/null 2>&1
exit 0
