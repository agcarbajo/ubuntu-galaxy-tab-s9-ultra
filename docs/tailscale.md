# Tailscale on Ubuntu 24.04

The kernel config has `CONFIG_TUN=m`. A connected `tailscaled` in
`--tun=userspace-networking` mode can answer `tailscale ping`, but ordinary
applications have no `tailscale0` route and the local MagicDNS resolver is not
reachable. A successful Tailscale status alone therefore does not prove that
web browsers can open tailnet URLs.

`scripts/build-tailscale-tun.sh` builds and signs `tun.ko` from the exact
kernel object tree. The normal kernel build stages it in `modules-root` for
fresh images. The device package also includes that same signed module, so an
existing installation gets it through the update package without a boot-image
write. `scripts/build-device-package.sh` rejects a module whose release or
signing certificate differs from the kernel build. Do not copy a module based
only on a matching `uname -r`.

On an installation that had the proxy-only flag, the device package's
`ubuntu-gts9u-tailscale-tun.service` runs after `tailscaled` on the next boot.
It loads TUN, replaces only `--tun=userspace-networking` with
`--tun=tailscale0`, restarts the daemon and enables tailnet DNS. It leaves the
authenticated Tailscale state and other daemon flags intact. If Tailscale is
not installed, or the flag is absent, the unit does nothing.

Check the complete path with:

```sh
ls -l /dev/net/tun
ip -4 address show dev tailscale0
tailscale status
resolvectl status tailscale0
getent ahostsv4 <peer>.<tailnet>.ts.net
curl -IL --max-time 15 https://<peer>.<tailnet>.ts.net/login
```

The LAN address is assigned by the router through DHCP. The device package's
`ubuntu-gts9u-wifi-address.service` reads Samsung's matching Wi-Fi address
copies from EFS read-only before NetworkManager starts, then supplies that
address as the default Wi-Fi MAC in a temporary `/run` configuration file.
It never writes EFS or ships a device-specific address. A connection profile
can override this default. The installed Wi-Fi profile uses DHCP with its
MAC as the DHCP client ID, so reconnects and tablet reboots identify the same
client to the router. The router may still change the lease, especially after
its own restart; an absolute address guarantee requires a router reservation.

The September 2026 live fix resolved the requested tailnet hostname and
received HTTP 200 from its HTTPS login page. Tailscale and the signed TUN
module survived an authorized reboot. The subsequent Wi-Fi fix switched the
installed profile back to DHCP and applied the EFS address. Validation is
recorded in `porting-log.md`.
