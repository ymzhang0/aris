#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARIS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PM2_SCRIPT="${SCRIPT_DIR}/pm2-dev.sh"
ARIS_URL="${ARIS_URL:-http://127.0.0.1:5173}"
API_URL="${ARIS_API_URL:-http://127.0.0.1:8000}"
WORKER_URL="${ARIS_WORKER_URL:-http://127.0.0.1:8001}"
WAIT_SECONDS="${ARIS_STARTUP_TIMEOUT:-45}"

usage() {
  cat <<'EOF'
Usage: ./scripts/aris-local.sh <command>

Commands:
  start     Start the production app services (worker + API)
  dev       Start worker, API, and Vite for live frontend development
  stop      Stop the local worker, API, and optional Vite service
  restart   Restart the production app services
  status    Show a concise service health summary
  doctor    Check local dependencies, paths, and service health
  logs      Follow logs for the local services
  open      Open the installed production ARIS application
  open-dev  Open a separate ARIS window connected to Vite
  build     Build the production frontend
  install   Build the frontend and install the standalone macOS application
EOF
}

http_ready() {
  local url="$1"
  curl --silent --show-error --fail --max-time 2 "${url}" >/dev/null 2>&1
}

wait_for_url() {
  local name="$1"
  local url="$2"
  local deadline=$((SECONDS + WAIT_SECONDS))

  while ((SECONDS < deadline)); do
    if http_ready "${url}"; then
      printf 'ready  %-12s %s\n' "${name}" "${url}"
      return 0
    fi
    sleep 1
  done

  printf 'failed %-12s %s\n' "${name}" "${url}" >&2
  return 1
}

start_app_services() {
  "${PM2_SCRIPT}" stop web >/dev/null 2>&1 || true
  if http_ready "${WORKER_URL}/status" && http_ready "${API_URL}/status" && http_ready "${API_URL}"; then
    printf 'ready  %-12s %s\n' "AiiDA worker" "${WORKER_URL}/status"
    printf 'ready  %-12s %s\n' "ARIS API" "${API_URL}/status"
    printf 'ready  %-12s %s\n' "ARIS app" "${API_URL}"
    return
  fi
  "${PM2_SCRIPT}" start core
  wait_for_url "AiiDA worker" "${WORKER_URL}/status"
  wait_for_url "ARIS API" "${API_URL}/status"
  wait_for_url "ARIS app" "${API_URL}"
}

start_dev_services() {
  "${PM2_SCRIPT}" start dev
  wait_for_url "AiiDA worker" "${WORKER_URL}/status"
  wait_for_url "ARIS API" "${API_URL}/status"
  wait_for_url "Vite" "${ARIS_URL}"
}

status_line() {
  local name="$1"
  local url="$2"
  if http_ready "${url}"; then
    printf 'online  %-12s %s\n' "${name}" "${url}"
  else
    printf 'offline %-12s %s\n' "${name}" "${url}"
  fi
}

doctor() {
  local failed=0
  local worker_dir
  worker_dir="${ARIS_WORKER_DIR:-$(cd "${ARIS_DIR}/.." && pwd)/aiida-worker}"

  for dependency in node npm npx uv curl; do
    if command -v "${dependency}" >/dev/null 2>&1; then
      printf 'ok      %-12s %s\n' "${dependency}" "$(command -v "${dependency}")"
    else
      printf 'missing %-12s\n' "${dependency}"
      failed=1
    fi
  done

  for required_path in \
    "${ARIS_DIR}/.venv/bin/python" \
    "${ARIS_DIR}/frontend/package.json" \
    "${worker_dir}/main.py"; do
    if [[ -e "${required_path}" ]]; then
      printf 'ok      path         %s\n' "${required_path}"
    else
      printf 'missing path         %s\n' "${required_path}"
      failed=1
    fi
  done

  status_line "AiiDA worker" "${WORKER_URL}/status"
  status_line "ARIS API" "${API_URL}/status"
  status_line "ARIS web" "${ARIS_URL}"
  return "${failed}"
}

main() {
  case "${1:-}" in
    start)
      start_app_services
      ;;
    dev)
      start_dev_services
      ;;
    stop)
      "${PM2_SCRIPT}" stop dev
      ;;
    restart)
      "${PM2_SCRIPT}" restart core
      "${PM2_SCRIPT}" stop web >/dev/null 2>&1 || true
      wait_for_url "AiiDA worker" "${WORKER_URL}/status"
      wait_for_url "ARIS API" "${API_URL}/status"
      wait_for_url "ARIS app" "${API_URL}"
      ;;
    status)
      status_line "AiiDA worker" "${WORKER_URL}/status"
      status_line "ARIS API" "${API_URL}/status"
      status_line "ARIS web" "${ARIS_URL}"
      ;;
    doctor)
      doctor
      ;;
    logs)
      "${PM2_SCRIPT}" logs dev
      ;;
    open)
      open "${HOME}/Applications/ARIS.app"
      ;;
    open-dev)
      start_dev_services
      open -n "${HOME}/Applications/ARIS.app" --args --dev
      ;;
    build)
      (cd "${ARIS_DIR}/frontend" && npm run build)
      ;;
    install)
      "${ARIS_DIR}/desktop/macos/install.sh"
      ;;
    ""|-h|--help|help)
      usage
      ;;
    *)
      echo "Unknown command: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
}

main "$@"
