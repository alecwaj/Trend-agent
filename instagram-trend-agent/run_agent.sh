#!/bin/bash
# run_agent.sh — Cron runner for Instagram Reels Trend Agent (LangChain)
#
# Runs every 2 hours for ~$1.80/day total spend (~$0.15/run × 12 runs).
# Budget tracker enforces the $2 daily ceiling — safe to schedule aggressively.
#
# Cron setup (every 2 hours):
#   0 */2 * * * /absolute/path/to/instagram-trend-agent/run_agent.sh
#
# Make executable first:
#   chmod +x run_agent.sh

set -euo pipefail

# ── Configuration ──────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
TODAY=$(date +%Y-%m-%d)
HOUR=$(date +%H)
LOG_FILE="${LOG_DIR}/${TODAY}.log"
VENV_DIR="${SCRIPT_DIR}/.venv"

# ── Activate virtual environment ───────────────────────────
if [ -f "${VENV_DIR}/bin/activate" ]; then
    source "${VENV_DIR}/bin/activate"
fi

# ── Ensure log directory exists ────────────────────────────
mkdir -p "${LOG_DIR}"

# ── Load .env file ─────────────────────────────────────────
if [ -f "${SCRIPT_DIR}/.env" ]; then
    set -a
    source "${SCRIPT_DIR}/.env"
    set +a
fi

# ── Run the agent ──────────────────────────────────────────
echo "=== Trend Agent starting at $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===" | tee -a "${LOG_FILE}"

cd "${SCRIPT_DIR}"

python agent.py --mode daily 2>&1 | tee -a "${LOG_FILE}"
EXIT_CODE=${PIPESTATUS[0]}

if [ ${EXIT_CODE} -eq 0 ]; then
    echo "=== Run SUCCEEDED at $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===" | tee -a "${LOG_FILE}"
else
    echo "=== Run FAILED (exit ${EXIT_CODE}) at $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===" | tee -a "${LOG_FILE}"
fi

# ── Rotate old logs (keep 30 days) ────────────────────────
find "${LOG_DIR}" -name "*.log" -mtime +30 -delete 2>/dev/null || true

exit ${EXIT_CODE}
