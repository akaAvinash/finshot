#!/usr/bin/env bash
# Merge one or more PR head commits, in order, into the checked-out base commit.
#
# Inputs (environment): HEAD_SHA (space-separated commits), FETCH_TOKEN (read token).
# The token is passed only to each fetch as a one-off extra header; nothing is stored
# in git config. Any failed fetch stops immediately (exit code of git), so a later
# head can never make a partly-built candidate look complete. A merge conflict
# aborts the merge and exits 3.
#
# The workflows copy this file out of the worktree before running it, so merging a
# candidate that edits this script cannot change the script mid-run.
set -euo pipefail

git config user.name qa-bot
git config user.email qa-bot@qa.tradeo.invalid
auth="AUTHORIZATION: basic $(printf 'x-access-token:%s' "${FETCH_TOKEN:-}" | base64 -w0)"
for sha in ${HEAD_SHA:-}; do
  if ! [[ "$sha" =~ ^[0-9a-f]{40}$ ]]; then
    echo "::error::not a full commit sha: $sha" >&2
    exit 2
  fi
  git -c "http.https://github.com/.extraheader=$auth" fetch --no-tags origin "$sha"
  if ! git merge --no-ff --no-edit "$sha"; then
    git merge --abort || true
    echo "::error::merge conflict applying $sha" >&2
    exit 3
  fi
done
