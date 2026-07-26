#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARIS_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BUILD_DIR="${ARIS_DIR}/desktop/macos/build"
APP_NAME="ARIS.app"
APP_DIR="${BUILD_DIR}/${APP_NAME}"
INSTALL_DIR="${ARIS_APP_INSTALL_DIR:-${HOME}/Applications}"
INSTALL_APP="${INSTALL_DIR}/${APP_NAME}"
ICON_SOURCE="${SCRIPT_DIR}/assets/aris.png"
ICONSET_DIR="${BUILD_DIR}/ARIS.iconset"

command -v clang >/dev/null 2>&1 || {
  echo "clang is required. Install the Xcode Command Line Tools first." >&2
  exit 1
}

mkdir -p "${APP_DIR}/Contents/MacOS" "${APP_DIR}/Contents/Resources"

(cd "${ARIS_DIR}/frontend" && npm run build)

if [[ -f "${ICON_SOURCE}" ]] && command -v iconutil >/dev/null 2>&1 && command -v sips >/dev/null 2>&1; then
  mkdir -p "${ICONSET_DIR}"
  sips -z 16 16 "${ICON_SOURCE}" --out "${ICONSET_DIR}/icon_16x16.png" >/dev/null
  sips -z 32 32 "${ICON_SOURCE}" --out "${ICONSET_DIR}/icon_16x16@2x.png" >/dev/null
  sips -z 32 32 "${ICON_SOURCE}" --out "${ICONSET_DIR}/icon_32x32.png" >/dev/null
  sips -z 64 64 "${ICON_SOURCE}" --out "${ICONSET_DIR}/icon_32x32@2x.png" >/dev/null
  sips -z 128 128 "${ICON_SOURCE}" --out "${ICONSET_DIR}/icon_128x128.png" >/dev/null
  sips -z 256 256 "${ICON_SOURCE}" --out "${ICONSET_DIR}/icon_128x128@2x.png" >/dev/null
  sips -z 256 256 "${ICON_SOURCE}" --out "${ICONSET_DIR}/icon_256x256.png" >/dev/null
  sips -z 512 512 "${ICON_SOURCE}" --out "${ICONSET_DIR}/icon_256x256@2x.png" >/dev/null
  sips -z 512 512 "${ICON_SOURCE}" --out "${ICONSET_DIR}/icon_512x512.png" >/dev/null
  cp "${ICON_SOURCE}" "${ICONSET_DIR}/icon_512x512@2x.png"
  iconutil -c icns "${ICONSET_DIR}" -o "${APP_DIR}/Contents/Resources/ARIS.icns"
fi

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
