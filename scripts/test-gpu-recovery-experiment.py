#!/usr/bin/env python3
"""Stage the GPU candidate and execute its real retry loops with mocked MMIO.

Usage: test-gpu-recovery-experiment.py PRISTINE_ADRENO_DIRECTORY
No GPU is accessed. This proves bounded control flow, not hardware recovery.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

repo = Path(__file__).resolve().parents[1]
original = Path(sys.argv[1])
stage = str(repo / "scripts/stage-gpu-recovery-experiment.sh")
names = ("a6xx_gmu.c", "a6xx_hfi.c")


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


with tempfile.TemporaryDirectory(prefix="gts9u-gpu-test-") as temporary:
    tree = Path(temporary)
    adreno = tree / "drivers/gpu/drm/msm/adreno"
    adreno.mkdir(parents=True)
    for name in names:
        (adreno / name).write_bytes((original / name).read_bytes())
    env = dict(os.environ, GPU_FAULT_WAIT_EXPERIMENTAL="0")
    run("bash", stage, temporary, env=env)
    for name in names:
        assert (adreno / name).read_bytes() == (original / name).read_bytes()
    env["GPU_FAULT_WAIT_EXPERIMENTAL"] = "1"
    run("bash", stage, temporary, env=env)
    staged = [(adreno / name).read_bytes() for name in names]
    run("bash", stage, temporary, env=env)
    assert staged == [(adreno / name).read_bytes() for name in names]
    env["GPU_FAULT_WAIT_EXPERIMENTAL"] = "0"
    assert subprocess.run(["bash", stage, temporary], env=env).returncode != 0

    for name in names:
        text = (adreno / name).read_text()
        marker = ("int a6xx_gmu_set_oob(" if name == "a6xx_gmu.c"
                  else "static int a6xx_hfi_wait_for_msg_interrupt(")
        start = text.index(marker)
        start = text.index("\tdo {", start)
        end = text.index("} while (true);", start) + len("} while (true);")
        loop = text[start:end]
        assert "wait_for_completion(" not in loop
        harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
static int polls, waits, capture_done, wait_result, succeed_on_poll;
static unsigned long waited_ms;
static struct { struct { int fault_coredump_done; } base; } object, *a6xx_gpu = &object;
static int fake_poll(void) {
    return ++polls == succeed_on_poll ? 0 : -ETIMEDOUT;
}
#define gmu_poll_timeout(gmu,reg,val,condition,delay,timeout) ((val)=0, fake_poll())
static int completion_done(int *unused) { (void)unused; return capture_done; }
static unsigned long msecs_to_jiffies(unsigned long ms) { return ms; }
static int wait_for_completion_timeout(int *unused, unsigned long timeout) {
    (void)unused; waits++; waited_ms=timeout; return wait_result;
}
static int transaction(void) {
    int ret; unsigned int val; bool waited_for_fault = false;
''' + loop + r'''
    (void)val;
    return ret;
}
static void check(int done, int result, int succeeds, int expected,
                  int expected_polls, int expected_waits) {
    polls=waits=0; waited_ms=0; capture_done=done;
    wait_result=result; succeed_on_poll=succeeds;
    assert(transaction()==expected);
    assert(polls==expected_polls && waits==expected_waits);
    if (waits) assert(waited_ms==1000);
}
int main(void) {
    check(0,0,1,0,1,0);                   /* Normal GMU response. */
    check(1,0,0,-ETIMEDOUT,1,0);          /* Timeout unrelated to capture. */
    check(0,0,0,-ETIMEDOUT,1,1);          /* Capture blocked on recovery lock. */
    check(0,1,2,0,2,1);                   /* Capture completes, retry works. */
    check(0,1,0,-ETIMEDOUT,2,1);          /* New faults cannot restart the loop. */
    return 0;
}
'''
        source = tree / "retry-test.c"
        source.write_text(harness)
        binary = tree / "retry-test"
        run("cc", "-std=c11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary))
        run(str(binary), timeout=5)
        print(f"PASS {name}: five transaction cases; bounded wait and retry")

    # A partial two-file patch must never pass staging or a default build.
    (adreno / names[0]).write_bytes((original / names[0]).read_bytes())
    for enabled in ("0", "1"):
        env["GPU_FAULT_WAIT_EXPERIMENTAL"] = enabled
        assert subprocess.run(["bash", stage, temporary], env=env).returncode != 0
    print("PASS staging: default, repeated opt-in, stale and partial rejection")
