#!/usr/bin/env bash
# Copy the homeid client library into the integration. Usage:
#   scripts/sync_library.sh /path/to/homeid-python
set -euo pipefail
source_repo=${1:?path to a homeid-python checkout}
target="$(dirname "$0")/../custom_components/homeid_airfryer/homeid"
rm -rf "$target"
mkdir -p "$target"
cp -R "$source_repo/src/homeid/." "$target/"
# The command line interface is not needed inside Home Assistant.
rm -f "$target/cli.py"
find "$target" -name __pycache__ -type d -prune -exec rm -rf {} +
commit=$(git -C "$source_repo" rev-parse HEAD)
dirty=$(git -C "$source_repo" status --porcelain -- src/homeid | head -c1)
printf 'homeid-python %s%s\n' "$commit" "${dirty:+ (with uncommitted changes)}" > "$target/SOURCE"
echo "Synced $commit into $target"
