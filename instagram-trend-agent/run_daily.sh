#!/bin/bash
# run_daily.sh — Daily cron runner for Instagram Reels Trend Agent
#
# Cron setup (runs at 6:00 AM UTC daily):
#   0 6 * * * /path/to/instagram-trend-agent/run_daily.sh
#
# Make executable:
#   chmod +x run_daily.sh

set -euo pipefail

# ── Configuration ──────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
TODAY=$(date +%Y-%m-%d)
LOG_FILE="${LOG_DIR}/${TODAY}.log"
VENV_DIR="${SCRIPT_DIR}/.venv"

# ── Activate virtual environment if it exists ──────────────
if [ -f "${VENV_DIR}/bin/activate" ]; then
    source "${VENV_DIR}/bin/activate"
fi

# ── Ensure log directory exists ────────────────────────────
mkdir -p "${LOG_DIR}"

# ── Load .env file if present ──────────────────────────────
if [ -f "${SCRIPT_DIR}/.env" ]; then
    set -a
    source "${SCRIPT_DIR}/.env"
    set +a
fi

# ── Run the agent ──────────────────────────────────────────
echo "=== Trend Agent starting at $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===" | tee -a "${LOG_FILE}"

cd "${SCRIPT_DIR}"

python main.py --mode daily 2>&1 | tee -a "${LOG_FILE}"
EXIT_CODE=${PIPESTATUS[0]}

if [ ${EXIT_CODE} -eq 0 ]; then
    echo "=== Run SUCCEEDED at $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===" | tee -a "${LOG_FILE}"
else
    echo "=== Run FAILED (exit ${EXIT_CODE}) at $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===" | tee -a "${LOG_FILE}"
fi

# ── Rotate old logs (keep 30 days) ────────────────────────
find "${LOG_DIR}" -name "*.log" -mtime +30 -delete 2>/dev/null || true

exit ${EXIT_CODE}
