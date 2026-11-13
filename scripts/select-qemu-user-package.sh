#!/bin/bash
# Resolve a real APT candidate; qemu-user-static is virtual on newer Ubuntu.
#
# On Noble `qemu-user-static` is the real package and it is what provides the
# static interpreter mmdebstrap needs.  On Questing and later the roles are
# reversed: `qemu-user-binfmt` provides the virtual `qemu-user-static` name and
# breaks the old real one, so `apt-get install qemu-user-static` aborts with
# nothing else from its command line installed either.
#
# The candidate is read without a pipeline on purpose.  `apt-cache policy`
# prints eleven lines for a package it knows; an awk that exits on the first
# match closes the pipe underneath it, apt-cache dies of SIGPIPE, and with
# `pipefail` that -- not awk's success -- is the pipeline's status.  The
# selector then exited 141 *after* reading the answer it wanted, on every host
# including Noble, and `set -e` in install-build-deps.sh turned that into an
# apt-get that never ran.  scripts/test-build-host-tools.py keeps it dead.
set -euo pipefail
for package in qemu-user-static qemu-user-binfmt qemu-user-binfmt-hwe; do
    policy=$(LC_ALL=C apt-cache policy "$package" 2>/dev/null) || continue
    candidate=$(awk '$1 == "Candidate:" { value = $2 } END { print value }' <<<"$policy")
    if [ -n "$candidate" ] && [ "$candidate" != '(none)' ]; then
        printf '%s\n' "$package"
        exit 0
    fi
done
echo 'No installable QEMU user-mode/binfmt package in the enabled APT repositories.' >&2
exit 1
