#!/bin/bash
# Resolve a real APT candidate; qemu-user-static is virtual on newer Ubuntu.
set -euo pipefail
for package in qemu-user-static qemu-user-binfmt qemu-user-binfmt-hwe; do
    candidate=$(LC_ALL=C apt-cache policy "$package" | awk '$1 == "Candidate:" { print $2; exit }')
    if [ -n "$candidate" ] && [ "$candidate" != '(none)' ]; then
        printf '%s\n' "$package"
        exit 0
    fi
done
echo 'No installable QEMU user-mode/binfmt package in the enabled APT repositories.' >&2
exit 1
