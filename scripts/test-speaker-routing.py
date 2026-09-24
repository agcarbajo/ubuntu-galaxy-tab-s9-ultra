#!/usr/bin/env python3
"""Check the packaged stereo speaker routing without touching hardware."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
card = (root / "packaging/ubuntu-gts9u-device/usr/share/alsa/ucm2/conf.d/sm8550/"
        "Samsung-Galaxy-Tab-S9-Ultra.conf").read_text()
hifi = (root / "packaging/ubuntu-gts9u-device/usr/share/alsa/ucm2/Qualcomm/"
        "sm8550/GTS9U/HiFi.conf").read_text()
controls = dict(re.findall(r'cset "name=\'([^\']+)\' ([^\"]+)"', card))
speaker_enable = hifi.split('SectionDevice."Speaker" {', 1)[1].split('DisableSequence', 1)[0]
unit = (root / "packaging/ubuntu-gts9u-device/usr/lib/systemd/system/"
        "ubuntu-gts9u-desktop-user.service").read_text()

for side, channel in (("Left", "ASP_RX1"), ("Right", "ASP_RX2")):
    for position in ("Front", "Rear"):
        prefix = f"{position} {side}"
        assert controls[f"{prefix} DACPCM Source"] == channel, prefix
        assert controls[f"{prefix} Digital PCM Volume"] == "420", prefix
        assert controls[f"{prefix} Analog PCM Volume"] == "3", prefix
        amp = f'cset "name=\'{prefix} AMP Enable Switch\' 1"'
        assert amp in speaker_enable
        for name, value in (("Digital PCM Volume", "420"),
                            ("Analog PCM Volume", "3"),
                            ("DACPCM Source", channel)):
            control = f'cset "name=\'{prefix} {name}\' {value}"'
            assert control in speaker_enable, control
            assert speaker_enable.index(control) < speaker_enable.index(amp)

assert "PlaybackChannels 2" in hifi
assert 'PlaybackPCM "hw:${CardId},0"' in hifi
assert "Wants=ubuntu-gts9u-adsp-boot.service alsa-restore.service" in unit
assert "ubuntu-gts9u-adsp-boot.service alsa-restore.service" in unit
helper = (root / "packaging/ubuntu-gts9u-device/usr/libexec/"
          "ubuntu-gts9u-desktop-user").read_text()
audio_ready = helper.split('if [ -e /dev/snd/controlC0 ]; then', 1)[1]
assert audio_ready.index('systemctl start alsa-restore.service') < audio_ready.index(
    'systemctl start "user@$uid.service"'
)
print("PASS: restore ALSA state before session startup and reapply stereo on Speaker enable")
