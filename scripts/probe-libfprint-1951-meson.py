#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Apply the EL721 Meson integration to a throwaway libfprint 1.95.1 tree."""
import argparse
from pathlib import Path


def replace_once(path, old, new):
    text = path.read_text()
    if text.count(old) != 1:
        raise ValueError(f"unexpected libfprint source: {path}: {old!r}")
    path.write_text(text.replace(old, new))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tree", type=Path)
    root = parser.parse_args().tree
    lib = root / "libfprint/meson.build"
    top = root / "meson.build"
    replace_once(lib, "    'elanspi': files('drivers/elanspi.c'),\n",
                 "    'elanspi': files('drivers/elanspi.c'),\n"
                 "    'el721': files('drivers/el721.c', 'drivers/el721-qtee.c'),\n")
    replace_once(lib, "    'udev': files(),\n",
                 "    'udev': files(),\n    'el721_qtee': files(),\n")
    replace_once(top, "    'focaltech_moc',\n]",
                 "    'focaltech_moc',\n    'el721',\n]")
    replace_once(top, "    'elanspi' : [ 'udev' ],\n",
                 "    'elanspi' : [ 'udev' ],\n"
                 "    'el721' : [ 'udev', 'el721_qtee' ],\n")
    replace_once(top, "        optional_deps += gudev_dep\n    endif\nendforeach",
                 "        optional_deps += gudev_dep\n"
                 "    elif i == 'el721_qtee'\n"
                 "        el721_qtee_root = meson.project_source_root() / 'el721-qtee-deps'\n"
                 "        el721_qtee_inc = include_directories('el721-qtee-deps/include')\n"
                 "        el721_qtee_lib = cc.find_library('qcomtee',\n"
                 "            dirs: el721_qtee_root / 'lib', static: true)\n"
                 "        el721_qcbor_lib = cc.find_library('qcbor',\n"
                 "            dirs: el721_qtee_root / 'lib', static: true)\n"
                 "        optional_deps += declare_dependency(\n"
                 "            dependencies: [el721_qtee_lib, el721_qcbor_lib, dependency('threads')],\n"
                 "            include_directories: el721_qtee_inc,\n"
                 "        )\n"
                 "    endif\nendforeach")
    print("EL721 Meson integration applied to", root)


if __name__ == "__main__":
    main()
