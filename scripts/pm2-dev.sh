#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARIS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ECOSYSTEM_FILE="${ARIS_PM2_ECOSYSTEM_FILE:-${ARIS_DIR}/ecosystem.config.js}"
PM2_CMD=(npx --yes pm2)
DEFAULT_TARGET="dev"
USER_NAME="$(id -un)"
USER_ID="$(id -u)"
HOME_DIR="${HOME}"
LAUNCH_AGENT_LABEL="pm2.${USER_NAME}"
LAUNCH_AGENT_DIR="${HOME_DIR}/Library/LaunchAgents"
LAUNCH_AGENT_FILE="${LAUNCH_AGENT_DIR}/${LAUNCH_AGENT_LABEL}.plist"
PM2_STDOUT_LOG="${HOME_DIR}/.pm2/pm2-launchd.log"
PM2_STDERR_LOG="${HOME_DIR}/.pm2/pm2-launchd.error.log"
NODE_BIN_DIR="$(dirname "$(command -v node)")"
NPX_BIN="$(command -v npx)"
PATH_VALUE="${NODE_BIN_DIR}:/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/pm2-dev.sh <command> [target]

Commands:
  start      Start one or more services from the PM2 ecosystem
  restart    Restart one or more services from the PM2 ecosystem
  stop       Stop one or more services from the PM2 ecosystem
  delete     Delete one or more services from PM2
  status     Show PM2 status for the selected services
  logs       Tail PM2 logs for the selected services
  save       Save the current PM2 process list
  startup    Configure a user-level launchd agent that runs 'pm2 resurrect' at login

Targets:
  dev        aris-api + aris-web (ARIS owns its worker subprocess)
  core       aris-api (ARIS owns its worker subprocess)
  api        aris-api
  web        aris-web
  all        entire ecosystem config

Examples:
  ./scripts/pm2-dev.sh start
  ./scripts/pm2-dev.sh restart
  ./scripts/pm2-dev.sh logs api
  ./scripts/pm2-dev.sh startup
EOF
}

require_ecosystem() {
  if [[ ! -f "${ECOSYSTEM_FILE}" ]]; then
    echo "Missing PM2 ecosystem file: ${ECOSYSTEM_FILE}" >&2
    exit 1
  fi
}

resolve_names() {
  local target="${1:-${DEFAULT_TARGET}}"
  case "${target}" in
    dev)
      printf '%s\n' "aris-api" "aris-web"
      ;;
    core)
      printf '%s\n' "aris-api"
      ;;
    api)
      printf '%s\n' "aris-api"
      ;;
    web)
      printf '%s\n' "aris-web"
      ;;
    all)
      printf '%s\n'
      ;;
    *)
      echo "Unknown target: ${target}" >&2
      usage
      exit 1
      ;;
  esac
}

pm2_start() {
  local target="${1:-${DEFAULT_TARGET}}"
  require_ecosystem
  if [[ "${target}" == "all" ]]; then
    (cd "${ARIS_DIR}" && "${PM2_CMD[@]}" start "${ECOSYSTEM_FILE}")
    return
  fi

  while IFS= read -r service; do
    [[ -n "${service}" ]] || continue
    (cd "${ARIS_DIR}" && "${PM2_CMD[@]}" start "${ECOSYSTEM_FILE}" --only "${service}")
  done < <(resolve_names "${target}")
}

pm2_restart() {
  local target="${1:-${DEFAULT_TARGET}}"
  require_ecosystem
  if [[ "${target}" == "all" ]]; then
    (cd "${ARIS_DIR}" && "${PM2_CMD[@]}" start "${ECOSYSTEM_FILE}")
    return
  fi

  while IFS= read -r service; do
    [[ -n "${service}" ]] || continue
    (cd "${ARIS_DIR}" && "${PM2_CMD[@]}" start "${ECOSYSTEM_FILE}" --only "${service}")
  done < <(resolve_names "${target}")
}

pm2_stop() {
  local target="${1:-${DEFAULT_TARGET}}"
  if [[ "${target}" == "all" ]]; then
    (cd "${ARIS_DIR}" && "${PM2_CMD[@]}" stop all)
    return
  fi

  while IFS= read -r service; do
    [[ -n "${service}" ]] || continue
    (cd "${ARIS_DIR}" && "${PM2_CMD[@]}" stop "${service}")
  done < <(resolve_names "${target}")
}

pm2_delete() {
  local target="${1:-${DEFAULT_TARGET}}"
  if [[ "${target}" == "all" ]]; then
    (cd "${ARIS_DIR}" && "${PM2_CMD[@]}" delete all)
    return
  fi

  while IFS= read -r service; do
    [[ -n "${service}" ]] || continue
    (cd "${ARIS_DIR}" && "${PM2_CMD[@]}" delete "${service}")
  done < <(resolve_names "${target}")
}

pm2_status() {
  local target="${1:-${DEFAULT_TARGET}}"
  if [[ "${target}" == "all" ]]; then
    (cd "${ARIS_DIR}" && "${PM2_CMD[@]}" list)
    return
  fi

  while IFS= read -r service; do
    [[ -n "${service}" ]] || continue
    echo "== ${service} =="
    (cd "${ARIS_DIR}" && "${PM2_CMD[@]}" show "${service}")
  done < <(resolve_names "${target}")
}

pm2_logs() {
  local target="${1:-${DEFAULT_TARGET}}"
  if [[ "${target}" == "all" ]]; then
    (cd "${ARIS_DIR}" && "${PM2_CMD[@]}" logs)
    return
  fi

  if [[ "${target}" == "core" ]]; then
    (cd "${ARIS_DIR}" && "${PM2_CMD[@]}" logs aris-api)
    return
  fi

  while IFS= read -r service; do
    [[ -n "${service}" ]] || continue
    (cd "${ARIS_DIR}" && "${PM2_CMD[@]}" logs "${service}")
  done < <(resolve_names "${target}")
}

pm2_save() {
  (cd "${ARIS_DIR}" && "${PM2_CMD[@]}" save)
}

pm2_startup() {
  mkdir -p "${LAUNCH_AGENT_DIR}" "${HOME_DIR}/.pm2"
  pm2_save

  cat > "${LAUNCH_AGENT_FILE}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>${LAUNCH_AGENT_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
      <string>${NPX_BIN}</string>
      <string>--yes</string>
      <string>pm2</string>
      <string>resurrect</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>EnvironmentVariables</key>
    <dict>
      <key>HOME</key>
      <string>${HOME_DIR}</string>
      <key>PATH</key>
      <string>${PATH_VALUE}</string>
    </dict>
    <key>WorkingDirectory</key>
    <string>${ARIS_DIR}</string>
    <key>StandardOutPath</key>
    <string>${PM2_STDOUT_LOG}</string>
    <key>StandardErrorPath</key>
    <string>${PM2_STDERR_LOG}</string>
  </dict>
</plist>
EOF

  launchctl bootout "gui/${USER_ID}" "${LAUNCH_AGENT_FILE}" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/${USER_ID}" "${LAUNCH_AGENT_FILE}"
  launchctl enable "gui/${USER_ID}/${LAUNCH_AGENT_LABEL}"
  launchctl kickstart -k "gui/${USER_ID}/${LAUNCH_AGENT_LABEL}" >/dev/null 2>&1 || true

  echo "Created ${LAUNCH_AGENT_FILE}"
  echo "launchd label: ${LAUNCH_AGENT_LABEL}"
}

main() {
  local command="${1:-}"
  local target="${2:-${DEFAULT_TARGET}}"

  case "${command}" in
    start)
      pm2_start "${target}"
      ;;
    restart)
      pm2_restart "${target}"
      ;;
    stop)
      pm2_stop "${target}"
      ;;
    delete)
      pm2_delete "${target}"
      ;;
    status)
      pm2_status "${target}"
      ;;
    logs)
      pm2_logs "${target}"
      ;;
    save)
      pm2_save
      ;;
    startup)
      pm2_startup
      ;;
    ""|-h|--help|help)
      usage
      ;;
    *)
      echo "Unknown command: ${command}" >&2
      usage
      exit 1
      ;;
  esac
}

main "$@"
