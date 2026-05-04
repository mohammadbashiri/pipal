#!/usr/bin/env bash
set -euo pipefail

OWNER_REPO="${1:-mohammadbashiri/pipal}"
MILESTONE_TITLE="M1: Thin Layer Foundation"
MILESTONE_DESC="Solid, useful, and extensible thin layer over pi with clear scope and reliable wrapper behavior."
MILESTONE_DUE="2026-06-30T23:59:59Z"

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI is required" >&2
  exit 1
fi

MS_NUMBER=$(gh api -X POST "repos/${OWNER_REPO}/milestones" \
  -f title="${MILESTONE_TITLE}" \
  -f state="open" \
  -f description="${MILESTONE_DESC}" \
  -f due_on="${MILESTONE_DUE}" \
  --jq '.number')

echo "Created milestone #${MS_NUMBER}"

create_issue () {
  local title="$1"
  local body_file="$2"
  gh issue create \
    --repo "${OWNER_REPO}" \
    --title "${title}" \
    --body-file "${body_file}" \
    --milestone "${MILESTONE_TITLE}" >/dev/null
  echo "Created issue: ${title}"
}

BASE="ops/github-backlog/m1-thin-layer-foundation/issues"
create_issue "Installation + Doctor Flow" "${BASE}/01-installation-and-doctor-flow.md"
create_issue "README Contract + Positioning" "${BASE}/02-readme-contract-and-positioning.md"
create_issue "Hardening: Scaffold, Registry, Sessions" "${BASE}/03-hardening-scaffold-registry-sessions.md"
create_issue "Hardening: Tasks + Daemon" "${BASE}/04-hardening-tasks-and-daemon.md"
create_issue "Server Safety Defaults + Optionality" "${BASE}/05-server-default-safety-and-optionality.md"
create_issue "Compatibility Matrix + Release Checklist" "${BASE}/06-compatibility-matrix-and-release-checklist.md"

echo "Backlog creation complete."
