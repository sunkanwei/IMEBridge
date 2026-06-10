#!/bin/bash

set -u
set -o pipefail

pause_and_exit() {
    local status="${1:-0}"
    if [ -t 0 ]; then
        echo
        read -r -p "Press Return to close this window..." _
    fi
    exit "$status"
}

fail() {
    echo
    echo "ERROR: $*"
    pause_and_exit 1
}

script_path="${BASH_SOURCE[0]}"
while [ -h "$script_path" ]; do
    script_dir="$(cd -P "$(dirname "$script_path")" >/dev/null 2>&1 && pwd)"
    script_path="$(readlink "$script_path")"
    [[ "$script_path" != /* ]] && script_path="$script_dir/$script_path"
done

EXT_DIR="$(cd -P "$(dirname "$script_path")" >/dev/null 2>&1 && pwd)" || fail "Could not resolve extension directory."
MANIFEST="$EXT_DIR/blender_manifest.toml"

[ -f "$MANIFEST" ] || fail "blender_manifest.toml was not found. Path: $MANIFEST"

find_blender() {
    if [ -n "${BLENDER_EXE:-}" ]; then
        [ -x "$BLENDER_EXE" ] && return 0
        fail "BLENDER_EXE is set but not executable: $BLENDER_EXE"
    fi

    local candidate
    for candidate in \
        "/Applications/Blender.app/Contents/MacOS/Blender" \
        "$EXT_DIR/../../../../Blender.app/Contents/MacOS/Blender"
    do
        if [ -x "$candidate" ]; then
            BLENDER_EXE="$candidate"
            return 0
        fi
    done

    local app
    for app in /Applications/Blender*.app; do
        candidate="$app/Contents/MacOS/Blender"
        if [ -x "$candidate" ]; then
            BLENDER_EXE="$candidate"
            return 0
        fi
    done

    candidate="$(command -v blender 2>/dev/null || true)"
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
        BLENDER_EXE="$candidate"
        return 0
    fi

    fail "Blender executable was not found. Install Blender in /Applications or set BLENDER_EXE."
}

manifest_value() {
    local key="$1"
    sed -nE "s/^[[:space:]]*$key[[:space:]]*=[[:space:]]*\"([^\"]+)\".*/\\1/p" "$MANIFEST" | head -n 1
}

check_manifest_python_paths() {
    local missing=""
    local file
    local rel

    while IFS= read -r file; do
        rel="${file#$EXT_DIR/}"
        if ! grep -Fq "\"$rel\"" "$MANIFEST"; then
            missing+="$rel"$'\n'
        fi
    done < <(find "$EXT_DIR" -type f -name "*.py" ! -path "*/__pycache__/*" ! -path "*/.serena/*" | sort)

    if [ -n "$missing" ]; then
        echo "ERROR: Python files missing from [build].paths:"
        printf "%s" "$missing" | sed 's/^/  /'
        pause_and_exit 1
    fi
}

check_package_contents() {
    if ! command -v unzip >/dev/null 2>&1; then
        echo "WARNING: unzip was not found; package content check was skipped."
        return 0
    fi

    local bad
    bad="$(unzip -Z1 "$ZIP_PATH" | grep -E '(^|/)README\.md$|(^|/)build_extension\.(bat|command|sh)$|(^|/)\.git(/|$)|(^|/)\.serena(/|$)|(^|/)\.DS_Store$|__pycache__|\.pyc$|\.(bat|command|sh)$' || true)"
    if [ -n "$bad" ]; then
        echo "ERROR: package contains excluded files:"
        printf "%s\n" "$bad" | sed 's/^/  /'
        pause_and_exit 1
    fi
}

find_blender

DESKTOP_DIR="$HOME/Desktop"
[ -d "$DESKTOP_DIR" ] || fail "Desktop directory was not found. Path: $DESKTOP_DIR"

EXT_ID="$(manifest_value id)"
EXT_VERSION="$(manifest_value version)"
[ -n "$EXT_ID" ] && [ -n "$EXT_VERSION" ] || fail "Could not read id/version from blender_manifest.toml."

ZIP_NAME="$EXT_ID-$EXT_VERSION.zip"
ZIP_PATH="$DESKTOP_DIR/$ZIP_NAME"

echo
echo "IMEBridge extension build"
echo "Source : $EXT_DIR"
echo "Blender: $BLENDER_EXE"
echo "Output : $ZIP_PATH"
echo

echo "Checking manifest Python paths..."
check_manifest_python_paths

echo "Checking package exclusions..."
echo "README.md, build scripts, .git, .serena, .DS_Store, __pycache__, and .pyc files are outside [build].paths."

if [ -f "$ZIP_PATH" ]; then
    echo "Removing previous package on Desktop..."
    rm -f "$ZIP_PATH" || fail "Could not remove previous package: $ZIP_PATH"
fi

echo
echo "Validating extension source..."
"$BLENDER_EXE" --factory-startup --command extension validate "$EXT_DIR" || fail "Validation failed."

echo
echo "Building extension package..."
"$BLENDER_EXE" --factory-startup --command extension build --source-dir "$EXT_DIR" --output-dir "$DESKTOP_DIR" --verbose || fail "Build failed."

[ -f "$ZIP_PATH" ] || fail "Build finished but the package was not found. Expected: $ZIP_PATH"

echo
echo "Checking package contents..."
check_package_contents

echo
echo "Done."
echo "Created: $ZIP_PATH"
echo
echo "The package is built by Blender's official extension command."
echo "README.md, build scripts, .git, .serena, .DS_Store, __pycache__, and .pyc files were not included."
pause_and_exit 0
