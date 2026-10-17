# ubuntu-gts9u-companion (transitional)

Tab Companion became [Galaxy Companion](https://github.com/agcarbajo/galaxy-companion)
on 2026-10-17 and is maintained there; this port pins the commit it ships as the
`external/galaxy-companion` submodule and builds the `galaxy-companion` package
from it (`scripts/build-companion-package.sh`).

This directory only holds the transitional `ubuntu-gts9u-companion` package:
empty, same version as the pinned Galaxy Companion, depending on it. Updaters
published before the rename require a package of that name in every update
payload, so it stays in the payload and in the image until no supported
installation runs Tab Companion any more. Galaxy Companion declares
`Replaces`/`Breaks` on the old versions and carries the settings over.
