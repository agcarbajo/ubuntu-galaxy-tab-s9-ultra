# Light sensor investigation: rooted One UI comparison

## 2026-09-09: working light stream identified

Tracing the One UI sensor HAL from process startup identified the missing
distinction: it discovers and enables **`auto_brightness`**, not the physical
`ambient_light` endpoint. The HAL receives changing lux readings through
SUID low `0x2b64ee57bea84411`, high `0x4f91fe8e66f4cd22`. Attributes identify
`STK31610 Light`, `SENSORTEK`, and `sns_ambient_light.proto`. Event 1025 has
eight packed floats; the first is the light level consumed by the HAL.

On a fresh Ubuntu boot with the original firmware, a standard on-change
request 514 to this endpoint returned **66 measurements in eight seconds**,
roughly 134–144 lux. No factory options, panel messages or firmware changes
were needed. The negative tests below describe the wrong endpoint and must
not be generalized to the board's light sensors.

`use-samsung-auto-brightness.patch` makes libssc discover this datatype when
the DT compatible list contains `samsung,gts9uwifi`. It retains the normal
`ambient_light` datatype on other boards and discovers the SUID normally;
there is no hardcoded SUID in the production patch. The iio-sensor-proxy build
restores the SSC light driver and requires the corrected libssc package.
The earlier synchronous-wait fix remains applied.

### Desktop validation and installation

The rebuilt `libssc 0.4.4-gts9u3` and `iio-sensor-proxy 3.9-gts9u3` were
installed on the tablet. `ssccli --sensor light` reports changing lux and
SensorProxy advertises `HasAmbientLight=true`. GNOME's existing
`org.gnome.settings-daemon.plugins.power ambient-enabled=true` setting
claimed the sensor without a separate brightness daemon.

The owner switched the room light off and on without moving the brightness
slider. Simultaneous D-Bus and backlight-sysfs measurements showed:

| Condition | Light level | Panel brightness (maximum 2047) |
| --- | --- | --- |
| Room lit, before test | approximately 135 lux | 608 |
| Room dark | 0 lux | 284 |
| Room lit again | approximately 150 lux | rose to 669 |

The owner also confirmed the visible increase. Motion regression probes
returned varying accelerometer and compass readings. With desktop sensor
clients active, iio-sensor-proxy consumed 1.47% of one CPU over 15 seconds
and the ADSP handover interrupt count did not increase.

The owner subsequently suspended with the power button and confirmed that
automatic brightness still worked after wake and unlock. Wi-Fi disappeared
during that cycle, preventing the immediate remote post-resume reading.
When SSH returned, the kernel log showed UFS PHY calibration failures and an
ext4 emergency read-only remount. This was not just a Wi-Fi failure: see the
[storage recovery and temporary suspend safeguard](resume-recovery.md).

The full ARM64 sensor-package build passed. Upstream general/light mock
tests were attempted in WSL but skipped (exit 77) because its kernel lacks
QIPCRTR; those skips are not reported as passing tests. The real tablet
checks above exercise the corrected board-specific selection and delivery.

For an existing installation, install both generated packages together and
restart the proxy:

```sh
sudo dpkg -i libssc_0.4.4-gts9u3_arm64.deb iio-sensor-proxy_3.9-gts9u3_arm64.deb
sudo systemctl restart iio-sensor-proxy
```

Future rootfs builds fingerprint the sensor patches and build script, so
they rebuild these packages automatically. No firmware or kernel change is
needed for this fix. Package SHA-256 values:

- libssc: `cc94f8a20a15d66e640a80bc2ab88029739e800a35c5e12dd3a1da2f1d53c1dd`
- iio-sensor-proxy: `fd8485c0b87c1ef7063829459629ddff072389403547e96d845e26ff5676d655`

The five sensors-PD libraries in the running One UI DSP partition are
byte-identical to Ubuntu's copies. A separate clean-boot trial with the
complete One UI ADSP/ADSP-DTB set restored working motion sensors but still
produced no physical `ambient_light` samples. The original firmware was
restored and its saved hashes verified before the successful stream test.

## 2026-09-08 baseline

On the physical tablet running kernel `7.2.0-rc3-dirty` build 8,
`ssccli -v --sensor light` still received a successful enable response and
no light samples during eight seconds. The accelerometer produced varying
samples in the subsequent four-second control. Automatic brightness remains
unfixed; the earlier rejected experiments are recorded in development-notes.md.

Before switching systems, the active Ubuntu boot partition and saved Ubuntu
boot image had identical SHA-256 digests. Tab Companion's boot switch wrote
and verified all four Android boot images and requested a reboot to One UI.
The owner unlocked One UI and authorized rooted USB ADB. Capture completed,
and the tablet returned to Ubuntu using the Android Dualboot application.

## Rooted One UI results

The SensorTek STK31610 exposes `lux` and six-component `raw_data` through
`/sys/class/sensors/light_sensor`. Sensorservice reports a standard light
sensor (handle 0x33) and Samsung auto-brightness sensor (handle 0x673).
The capture contains changing ambient readings. A separate raw QRTR client
sent standard request 514 to the physical light SUID and received 60 light
events (1025) in eight seconds. The standard protocol therefore works in
the initialized One UI environment.

The live STK/light registry entries match Ubuntu semantically, including
factory calibration; numeric string formatting differs. Do not repeat the
rejected bus, rail and polling changes on this evidence.

Tracing `factory.ssc` and the sensor HAL during screen off/on revealed:

| Target | Message | Payload values |
| --- | --- | --- |
| Light | 615 | int32 array `[2, screen_on, 0]` |
| SSC Core | 615 | int32 array `[3, screen_on]` |
| Light | 611 | int32 brightness |
| SSC Core | 512 | standard sample rate float 10 |

The factory option envelope uses field 1 varint 4 and field 2 packed little
endian int32 bytes. Brightness uses field 1 varint 2. The SUID pairs below
are the low/high uint64 values, not host-rendered wire byte strings:

- Light: `0x2a462eac2a9a1071`, `0x4795ecea145f6a96`.
- SSC Core: `0x7766554433221100`, `0x1255080808120310`.

**Correction to the earlier discovery hypothesis:** SSC Core exists through
a hardcoded SUID even though datatype discovery did not return it.

Ubuntu accepts the captured options and brightness messages and returns
factory response events, but still delivers zero physical-light samples.
The combined probe also receives an event 1025 from **SSC Core**; filtering
the source SUID is essential to avoid counting this as a light reading.
An independent `ssccli --sensor light` check also produced no samples.

## Firmware comparison and rejected runtime trial

One UI's ADSP and ADSP DTB both differ from the Ubuntu payload. The current
device's `apnhlos` partition was mounted read-only and matched the Android
capture. A complete ADSP/ADSP-DTB pair was copied into a temporary `/run`
firmware lookup directory and tested by restarting remoteproc. This did
not publish SSC service 400, even after restarting sensorspd; audio also
reported command timeouts. This is not a valid working firmware update and
does not establish whether a matched firmware/library set would work at
cold boot. No replacement was made in `/lib/firmware` or any boot image.
The temporary lookup override was cleared and Ubuntu was rebooted.
After that reboot the override was empty, ADSP was running, the accelerometer
again delivered varying samples, and the Samsung ALSA sound card was present.
This verifies sensor recovery and sound-card enumeration, not audible playback.

This was the unresolved checkpoint before the 2026-09-09 startup capture
above. Do not ship the unsuccessful runtime substitution or screen messages
as an ALS fix: selecting the HAL's actual light datatype resolves delivery.

## Resume

Run `scripts/capture-oneui-light-reference.py SERIAL LOCAL_OUTPUT_DIRECTORY`
after ADB is authorized and Magisk grants root. The script verifies SM-X910
identity, then records sensorservice/display state, the sensor processes,
light sysfs attributes and ten samples, registry paths, relevant logs and
firmware hashes. Keep the output in ignored `work/`, not in public Git.

Raw captures, traces and firmware stay under ignored `work/`; they contain
device-specific calibration and must not be published. The Ubuntu baseline
is saved on the tablet under `/home/agcar/als-ubuntu-reference-20260908`.

Return through the existing dualboot mechanism when capture is finished;
the verified saved Ubuntu image preserves the running build 8 kernel.
