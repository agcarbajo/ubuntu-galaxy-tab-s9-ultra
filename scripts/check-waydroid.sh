#!/bin/bash
# Read-only checks of an already running official GAPPS Waydroid session.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo 'Run as root after starting Waydroid.' >&2; exit 1; }
test "$(waydroid shell -- getprop sys.boot_completed | tr -d '\r\n')" = 1
packages=$(waydroid shell -- pm list packages)
for package in com.google.android.gms com.google.android.gsf com.android.vending; do
	grep -qx "package:$package" <<< "$packages"
done
https=$(waydroid shell -- curl -sS --max-time 20 -o /dev/null \
	-w '%{http_code} %{ssl_verify_result}' https://connectivitycheck.gstatic.com/generate_204)
test "$https" = '204 0'
connectivity=$(waydroid shell -- dumpsys connectivity)
grep -q 'INTERNET.*VALIDATED' <<< "$connectivity"
graphics=$(waydroid shell -- dumpsys SurfaceFlinger)
grep -E '^GLES:.*freedreno.*FD740' <<< "$graphics"
printf 'PASS: Android boot, Google packages, DNS/HTTPS/TLS, validated Internet, Adreno 740 rendering\n'
printf 'Google account sign-in and Play certification are separate user checks.\n'
