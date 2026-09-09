#!/usr/bin/env python3
"""Test staging and execute the real calibration function with mocked MMIO.

Usage: python3 scripts/test-ufs-resume-experiment.py PRISTINE_QMP_UFS_C
This never accesses a PHY or suspends the host. Passing tests is not physical
resume validation, nor a replacement for building the complete driver.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

repo = Path(__file__).resolve().parents[1]
original = Path(sys.argv[1]).read_text()


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


with tempfile.TemporaryDirectory(prefix="gts9u-ufs-test-") as tmp:
    tree = Path(tmp)
    source = tree / "drivers/phy/qualcomm/phy-qcom-qmp-ufs.c"
    source.parent.mkdir(parents=True)
    source.write_text(original)
    baseline = repo / "kernel/patches/qmp-ufs-reset-serdes-before-power-down-gts9u.patch"
    run("patch", "--batch", "--fuzz=0", "-d", tmp, "-p1", input=baseline.read_text())
    staged = source.read_bytes()
    orig = source.with_suffix(".c.orig")
    orig.write_bytes(b"Pre-existing developer backup; preserve it.\n")
    stage = str(repo / "scripts/stage-ufs-resume-experiment.sh")
    env = dict(os.environ, UFS_PCS_RESET_EXPERIMENTAL="0")
    run("bash", stage, tmp, env=env)
    assert source.read_bytes() == staged, "explicit opt-out changed PHY"
    env.pop("UFS_PCS_RESET_EXPERIMENTAL", None)  # Release default must apply the validated fix.
    run("bash", stage, tmp, env=env)
    candidate = source.read_bytes()
    assert orig.read_bytes() == b"Pre-existing developer backup; preserve it.\n"
    run("bash", stage, tmp, env=env)
    assert source.read_bytes() == candidate, "repeat staging is not idempotent"
    for value in ("0", "invalid"):
        env["UFS_PCS_RESET_EXPERIMENTAL"] = value
        result = subprocess.run(["bash", stage, tmp], env=env, capture_output=True)
        assert result.returncode != 0, f"accepted unsafe option/tree {value}"
        assert source.read_bytes() == candidate

    # A comment alone must not make a damaged experiment look installed.
    damaged = candidate.replace(
        b'\t\tqphy_setbits(pcs, cfg->regs[QPHY_SW_RESET], SW_RESET);',
        b'\t\tqphy_setbits(pcs, cfg->regs[QPHY_SW_RESET], 0);')
    assert damaged != candidate
    source.write_bytes(damaged)
    env["UFS_PCS_RESET_EXPERIMENTAL"] = "1"
    result = subprocess.run(["bash", stage, tmp], env=env, capture_output=True)
    assert result.returncode != 0, "accepted a damaged reset sequence"
    assert source.read_bytes() == damaged
    source.write_bytes(candidate)

    match = re.search(r"static int qmp_ufs_phy_calibrate\(struct phy \*phy\)\n\{.*?\n\}",
                      candidate.decode(), re.S)
    assert match, "calibration function not found"
    harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#define __iomem
#define SW_RESET 1
#define SERDES_START 1
#define PCS_READY 1
#define PHY_INIT_COMPLETE_TIMEOUT 10000
enum { QPHY_SW_RESET, QPHY_START_CTRL, QPHY_PCS_READY_STATUS };
struct qmp_phy_cfg { bool no_pcs_sw_reset; unsigned regs[3]; };
static const struct qmp_phy_cfg sm8550_ufsphy_cfg = {false, {0, 4, 8}};
static const struct qmp_phy_cfg other_cfg = {false, {0, 4, 8}};
static const struct qmp_phy_cfg no_pcs_cfg = {true, {0, 4, 8}};
struct qmp_ufs { const struct qmp_phy_cfg *cfg; void *pcs, *ufs_reset, *dev; };
struct phy { struct qmp_ufs *qmp; };
static bool board;
static int assert_error, deassert_error, poll_error;
static char trace[64];
static void event(char c) { size_t n = strlen(trace); trace[n] = c; trace[n+1] = 0; }
static struct qmp_ufs *phy_get_drvdata(struct phy *p) { return p->qmp; }
static int of_machine_is_compatible(const char *s) {
    assert(!strcmp(s, "samsung,gts9uwifi")); return board;
}
static int reset_control_assert(void *p) { (void)p; event('A'); return assert_error; }
static int reset_control_deassert(void *p) { (void)p; event('D'); return deassert_error; }
static void qphy_setbits(void *p, unsigned r, unsigned v) {
    (void)p; (void)v; event(r == 0 ? 'R' : 'S');
}
static void qphy_clrbits(void *p, unsigned r, unsigned v) {
    (void)p; (void)r; (void)v; event('C');
}
static void qmp_ufs_init_registers(struct qmp_ufs *q, const struct qmp_phy_cfg *c) {
    (void)q; (void)c; event('T');
}
#define readl_poll_timeout(addr, val, cond, delay, timeout) \
    ((void)(addr), (val) = 1, (void)(cond), event('P'), poll_error)
#define dev_err(...) event('E')
'''
    harness += match.group(0)
    harness += r'''
static void check(const struct qmp_phy_cfg *cfg, bool is_board,
                  int ae, int de, int pe, int expected, const char *events) {
    char pcs[16];
    struct qmp_ufs q = { .cfg = cfg, .pcs = pcs };
    struct phy phy = { &q };
    trace[0] = 0; board = is_board;
    assert_error = ae; deassert_error = de; poll_error = pe;
    assert(qmp_ufs_phy_calibrate(&phy) == expected);
    assert(!strcmp(trace, events));
}
int main(void) {
    for (int i = 0; i < 3; i++)
        check(&sm8550_ufsphy_cfg, true, 0, 0, 0, 0, "ARTDCSP");
    check(&sm8550_ufsphy_cfg, false, 0, 0, 0, 0, "ATDCSP");
    check(&other_cfg, true, 0, 0, 0, 0, "ATDCSP");
    check(&no_pcs_cfg, true, 0, 0, 0, 0, "ATDSP");
    check(&sm8550_ufsphy_cfg, true, -5, 0, 0, -5, "A");
    check(&sm8550_ufsphy_cfg, true, 0, -5, 0, -5, "ARTD");
    check(&sm8550_ufsphy_cfg, true, 0, 0, -110, -110, "ARTDCSPE");
    puts("PASS: calibration ordering, repeated cycles, platform guards, error propagation");
}
'''
    test_c = tree / "calibrate-test.c"
    test_c.write_text(harness)
    exe = tree / "calibrate-test"
    run("cc", "-std=gnu11", "-Wall", "-Wextra", "-Werror", str(test_c), "-o", str(exe))
    run(str(exe))
    print("PASS: explicit opt-out unchanged, strict patch application, repeat staging, stale-tree refusal")
