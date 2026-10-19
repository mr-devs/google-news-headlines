#!/bin/bash
#
# Git Backup Script
#
# Purpose:
#   Automatically commits and pushes any changes in the repository.
#   Used by cron to backup data at scheduled intervals.
#

# Use full path to git for cron reliability
GIT=/usr/bin/git

# Repository root is the parent of this script's directory (scripts/)
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

# Check for any changes (modified, new, or deleted files)
# git status --porcelain returns output if there are any changes
if [ -n "$($GIT status --porcelain)" ]; then
    $GIT add -A
    $GIT commit -m "data backup $(date '+%Y-%m-%d %H:%M')"
    $GIT push
    echo "$(date): Backup completed - changes pushed"
else
    echo "$(date): No changes to backup"
fi
