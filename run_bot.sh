#!/usr/bin/env bash
# One-command launcher for the BatchLeads Bot
set -e
cd "$(dirname "$0")"

echo "=== BatchLeads Bot Setup ==="

# Install Python deps if needed
if ! python3 -c "import playwright" 2>/dev/null; then
  echo "Installing dependencies..."
  pip install -r requirements.txt -q
  python3 -m playwright install chromium
fi

echo "Starting control panel at http://localhost:5000"
echo "Press Ctrl+C to stop."
python3 app.py
