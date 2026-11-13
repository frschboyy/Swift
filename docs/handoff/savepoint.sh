#!/usr/bin/env bash
# Save point: copy every worktree's uncommitted work onto a branch, without touching the worktree.
#
# For each worktree with uncommitted changes on branch claude/<name>, this writes one commit on
# savepoint/<name> whose parent is the worktree's HEAD. The worktree, its index and its branch are
# left exactly as they were, so it is safe while sessions are still running. Run it again just
# before pushing: it overwrites the savepoint/* branches with the newest state.
#
#   bash docs/handoff/savepoint.sh            # snapshot, then print the push command
#
# Restore on the other computer: see docs/handoff/savepoint-2026-11-13.md.
set -euo pipefail

common=$(git rev-parse --path-format=absolute --git-common-dir)
stamp=$(date '+%Y-%m-%d %H:%M')
branches=()
# No git identity on this machine? Reuse the author of the last commit, as the sessions do.
if ! git config user.email >/dev/null; then
  GIT_AUTHOR_NAME=$(git log -1 --format=%an); GIT_AUTHOR_EMAIL=$(git log -1 --format=%ae)
  export GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME=$GIT_AUTHOR_NAME GIT_COMMITTER_EMAIL=$GIT_AUTHOR_EMAIL
fi

while IFS=$'\t' read -r wt ref; do
  [ -d "$wt" ] || continue
  br=${ref#refs/heads/}
  [ "$br" = main ] && continue          # main's untracked files are not Swift work
  branches+=("$br")
  save="savepoint/${br#claude/}"
  if [ -z "$(git -C "$wt" status --porcelain)" ]; then
    # A session may have committed since the last snapshot; don't leave an older
    # WIP tree that could overwrite the newer branch when restored.
    if git show-ref --verify --quiet "refs/heads/$save"; then
      git -C "$wt" update-ref "refs/heads/$save" HEAD
      echo "current $br -> $save (clean)"
      branches+=("$save")
    fi
    continue
  fi
  idx=$(mktemp -u)
  GIT_INDEX_FILE="$idx" git -C "$wt" read-tree HEAD
  GIT_INDEX_FILE="$idx" git -C "$wt" add -A
  tree=$(GIT_INDEX_FILE="$idx" git -C "$wt" write-tree)
  rm -f "$idx"
  msg="WIP save point of $br ($stamp): uncommitted work, unreviewed and maybe failing

Restore it as uncommitted changes: git checkout $br && git restore --source=$save -- . (see docs/handoff/savepoint-2026-11-13.md)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
  commit=$(git -C "$wt" commit-tree "$tree" -p HEAD -m "$msg")
  git -C "$wt" update-ref "refs/heads/$save" "$commit"
  echo "saved   $br -> $save ($(git -C "$wt" diff --stat HEAD "$commit" | tail -1))"
  branches+=("$save")
done < <(git --git-dir="$common" worktree list --porcelain \
          | awk '/^worktree /{w=substr($0,10)} /^branch /{print w "\t" substr($0,8)}')

echo
echo "Push with:"
echo "  git push origin main ${branches[*]}"
