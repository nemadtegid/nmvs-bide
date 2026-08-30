#!/bin/sh
set -e

PROJECT_DIR=<write-here-project-absolute-dir-path>
SECRETS="$PROJECT_DIR/.secrets.env"
PYTHON="$PROJECT_DIR/venv/bin/python"
LOG="$PROJECT_DIR/logs/nmvs-cron-client.log"

[ -f "$SECRETS" ] && . "$SECRETS"
cd "$PROJECT_DIR"
. venv/bin/activate
source "$SECRETS"

# run report(s). Add more lines as you see fit for your needs.
"$PYTHON" -m nmvs.client.client -n ExceptionsAuditTrailReport >> "$LOG" 2>&1