#!/bin/bash
# How fast is the internal UFS, and what is its inline crypto engine clocked
# at?  Reads the root partition directly and nothing else, unless --write is
# given: then it also writes one temporary 1 GiB file and removes it.
#
#   sudo ufs-throughput.sh [--write] [--verify FILE SHA256]
#
# --verify reads FILE back with a cold page cache and compares its SHA-256,
# which is the check that a faster clock still returns the right bytes.
set -u
export LC_ALL=C
write=0 verify_file='' verify_sum=''
while [ $# -gt 0 ]; do
	case "$1" in
		--write) write=1; shift ;;
		--verify) verify_file=${2:?--verify FILE SHA256}; verify_sum=${3:?--verify FILE SHA256}; shift 3 ;;
		*) echo "usage: ufs-throughput.sh [--write] [--verify FILE SHA256]" >&2; exit 2 ;;
	esac
done
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
dev=$(findmnt -no SOURCE / | sed 's/\[.*//')
host=$(ls -d /sys/devices/platform/soc@0/*ufshc* 2>/dev/null | head -1)
clk=/sys/kernel/debug/clk/gcc_ufs_phy_ice_core_clk_src
mountpoint -q /sys/kernel/debug || mount -t debugfs none /sys/kernel/debug 2>/dev/null
if [ -r "$clk/clk_rate" ]; then
	echo "ICE core clock: $(cat "$clk/clk_rate") Hz, parent $(cat "$clk/clk_parent" 2>/dev/null)"
else
	echo "ICE core clock: not visible (no debugfs clock tree)"
fi
[ -n "$host" ] && echo "link at rest: $(cat "$host/power_info/gear") on $(cat "$host/power_info/lane") lanes; queue depth $(cat /sys/block/sda/device/queue_depth 2>/dev/null)"
python3 - "$dev" "$host" "$write" <<'PY'
import mmap, os, random, sys, threading, time
dev, host, write = sys.argv[1], sys.argv[2], sys.argv[3] == '1'
MiB = 1 << 20

def stream(offset_mib, total_mib):
    fd = os.open(dev, os.O_RDONLY | os.O_DIRECT)
    buf = mmap.mmap(-1, MiB)
    done = 0
    while done < total_mib * MiB:
        n = os.preadv(fd, [buf], offset_mib * MiB + done)
        if n <= 0:
            break
        done += n
    os.close(fd)
    return done

def sequential(readers, total_mib):
    # The same regions on every run, so that two runs can be compared.
    results, gear = [], '?'
    threads = [threading.Thread(target=lambda i=i: results.append(stream(8000 + i * 6000, total_mib)))
               for i in range(readers)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    time.sleep(0.5)
    if host:
        gear = open(host + '/power_info/gear').read().strip()
    for t in threads:
        t.join()
    return sum(results) / 1e6 / (time.perf_counter() - start), gear

for readers, mib in ((1, 2000), (4, 1000), (8, 700), (16, 450)):
    rate, gear = max(sequential(readers, mib) for _ in range(2))
    print("sequential read, %2d reader%s of 1 MiB: %5.0f MB/s (%s under load)"
          % (readers, ' ' if readers == 1 else 's', rate, gear))

fd = os.open(dev, os.O_RDONLY | os.O_DIRECT)
size = os.lseek(fd, 0, os.SEEK_END)
buf = mmap.mmap(-1, 4096)
random.seed(7)
latency = []
for _ in range(3000):
    offset = random.randrange(0, size // 4096) * 4096
    start = time.perf_counter()
    os.preadv(fd, [buf], offset)
    latency.append(time.perf_counter() - start)
os.close(fd)
latency.sort()
print("4 KiB random read, depth 1: median %.0f us, p99 %.0f us"
      % (latency[len(latency) // 2] * 1e6, latency[int(len(latency) * 0.99)] * 1e6))

if write:
    stat = os.statvfs('/var/tmp')
    if stat.f_bavail * stat.f_frsize < 6 << 30:
        print("sequential write: skipped, under 6 GiB free on /var/tmp")
    else:
        path = '/var/tmp/gts9u-ufs-throughput.bin'
        data = mmap.mmap(-1, 4 * MiB)
        data.write(os.urandom(4 * MiB))
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_DIRECT, 0o600)
        try:
            start = time.perf_counter()
            done = 0
            while done < 1024 * MiB:
                done += os.pwritev(fd, [data], done)
            os.fsync(fd)
            print("sequential write, 1 GiB in 4 MiB pieces: %5.0f MB/s"
                  % (done / 1e6 / (time.perf_counter() - start)))
        finally:
            os.close(fd)
            os.unlink(path)
PY
if [ -n "$verify_file" ]; then
	sync
	echo 3 > /proc/sys/vm/drop_caches
	start=$(date +%s.%N)
	got=$(sha256sum "$verify_file" | cut -d' ' -f1)
	end=$(date +%s.%N)
	if [ "$got" = "$verify_sum" ]; then
		awk -v a="$start" -v b="$end" -v s="$(stat -c %s "$verify_file")" \
			'BEGIN { printf "verify: right SHA-256, %.0f MB/s including the hashing\n", s / 1e6 / (b - a) }'
	else
		echo "verify: SHA-256 MISMATCH, got $got"
		exit 1
	fi
fi
echo "I/O complaints in the kernel log this boot: $(dmesg | grep -ciE 'I/O error|EXT4-fs error|Remounting filesystem read-only')"
