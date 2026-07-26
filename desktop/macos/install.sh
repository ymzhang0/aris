#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARIS_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BUILD_DIR="${ARIS_DIR}/desktop/macos/build"
APP_NAME="ARIS.app"
APP_DIR="${BUILD_DIR}/${APP_NAME}"
INSTALL_DIR="${ARIS_APP_INSTALL_DIR:-${HOME}/Applications}"
INSTALL_APP="${INSTALL_DIR}/${APP_NAME}"

command -v clang >/dev/null 2>&1 || {
  echo "clang is required. Install the Xcode Command Line Tools first." >&2
  exit 1
}

mkdir -p "${APP_DIR}/Contents/MacOS" "${APP_DIR}/Contents/Resources"

(cd "${ARIS_DIR}/frontend" && npm run build)

CLANG_MODULE_CACHE_PATH="${CLANG_MODULE_CACHE_PATH:-${BUILD_DIR}/module-cache}" \
clang \
  -fobjc-arc \
  "${SCRIPT_DIR}/main.m" \
  -framework AppKit \
  -framework WebKit \
  -o "${APP_DIR}/Contents/MacOS/ARIS"

sed "s|__ARIS_REPO_PATH__|${ARIS_DIR}|g" "${SCRIPT_DIR}/Info.plist.in" > "${APP_DIR}/Contents/Info.plist"

mkdir -p "${INSTALL_DIR}"
if [[ -e "${INSTALL_APP}" ]]; then
  BACKUP_APP="${INSTALL_APP}.previous-$(date +%Y%m%d-%H%M%S)"
  mv "${INSTALL_APP}" "${BACKUP_APP}"
  echo "Previous application moved to ${BACKUP_APP}"
fi
cp -R "${APP_DIR}" "${INSTALL_APP}"

echo "Installed ${INSTALL_APP}"
echo "Open ARIS from Finder or Spotlight."
