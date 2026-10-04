# SPDX-License-Identifier: MIT
"""User-visible S Pen link phases, including while the pen is docked."""


def remote_status_phase(*, bluetooth, enabled, docked, paired, connected, ready,
                        pairing_active=False):
    if not bluetooth:
        return "bluetooth-off"
    if not enabled:
        return "remote-off"
    # BlueZ Connected is not proof that Samsung GATT is working. The hardware
    # service sets ready only after a successful live operation.
    if connected and ready:
        return "ready"
    if connected:
        return "preparing"
    if paired:
        return "reconnecting" if docked else "sleeping"
    if docked:
        return "pairing" if pairing_active else "pairing-needed"
    return "unpaired"
