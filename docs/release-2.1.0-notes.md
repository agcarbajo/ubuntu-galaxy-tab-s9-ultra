- Starts in less than half the time: the login screen is ready in about 13 s instead of 30 s.
- Internal storage about five times faster: sequential writes near 1.6 GB/s and reads up to 1.3 GB/s.
- Galaxy Companion 1.0.1: the update check works again and S Pen features survive Bluetooth updates.
- Fingerprint set-up fixes for other units, and `sudo gts9u-fingerprint-check` to report a reader that is not detected.
- Wi-Fi is brought back more reliably after suspend; a storage failure after deep suspend is announced and not repeated.
- GNOME extensions come back after a Shell failure in every session mode, and the TWRP installer verifies what it writes.

Figures measured on the development tablet.

**Updating from 2.0.0:** open Galaxy Companion → Updates.

**Upgrading from Ubuntu 24.04 (1.3.0 or earlier):** this build updates Ubuntu 26.04 installations only. Follow the [update guide](https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra#updating-an-existing-installation), which goes through 2.0.0 first.

Thanks to @jstockdale for the storage diagnosis and the reports in #13, and to @RobiiAragon for the build-host and Bluetooth fixes.

<!-- gts9u-update-format: 2 -->
