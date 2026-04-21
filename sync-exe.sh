#!/usr/bin/env bash
# sync-exe.sh — Wait for CI to build, then download the release exe.
# Can be run standalone or triggered automatically after git push.

set -euo pipefail

export PATH="$PATH:/c/Program Files/GitHub CLI"

REPO="Z3nGineer/HeatSync"
DEST="$HOME/Apps/HeatSync"
VERSION=$(cat "$(dirname "$0")/VERSION")
TAG="v${VERSION}"

echo "[sync-exe] Waiting for CI to finish building ${TAG}..."

# Poll the latest Build workflow run until it completes (up to 15 min)
for _ in $(seq 1 90); do
    STATUS=$(gh api "repos/$REPO/actions/runs?per_page=1&branch=main" \
        --jq '.workflow_runs[] | select(.name | contains("Build")) | .status' 2>/dev/null || echo "unknown")
    if [ "$STATUS" = "completed" ]; then
        break
    fi
    sleep 10
done

if [ "$STATUS" != "completed" ]; then
    echo "[sync-exe] CI did not complete in time."
    exit 1
fi

# Wait for the release to appear
echo "[sync-exe] Waiting for release ${TAG}..."
for _ in $(seq 1 30); do
    if gh release view "$TAG" --repo "$REPO" &>/dev/null; then
        break
    fi
    sleep 10
done

if ! gh release view "$TAG" --repo "$REPO" &>/dev/null; then
    echo "[sync-exe] Release ${TAG} not found after waiting."
    exit 1
fi

mkdir -p "$DEST"
gh release download "$TAG" --repo "$REPO" --pattern "HeatSync.exe" --dir "$DEST" --clobber
echo "[sync-exe] Updated ${DEST}/HeatSync.exe to ${TAG}"
