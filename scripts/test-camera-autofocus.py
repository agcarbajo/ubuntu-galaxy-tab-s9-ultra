#!/usr/bin/env python3
"""Test the production AF state machine with synthetic lens/contrast curves.

This does not certify optical sharpness or actual actuator settling time.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

source = Path(sys.argv[1]).read_text()
fields = source[source.index("\tenum class AfPhase"):source.index("\t/* Local parameter storage */")]
start = source.index("void IPASoftSimple::startFocusScan()")
methods = source[start:source.index("std::string IPASoftSimple::logPrefix()", start)]
harness = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <optional>
namespace controls {
constexpr int AfModeContinuous=2, AfModeAuto=1;
constexpr int AfStateIdle=0, AfStateScanning=1, AfStateFocused=2, AfStateFailed=3;
}
struct IPASoftSimple {
void startFocusScan();
std::optional<int32_t> processFocusStats(uint64_t);
''' + fields + "};\n" + methods + r'''
uint64_t curve(int position, int target) {
    double d = (position-target)/120.0;
    return 1000 + static_cast<uint64_t>(9000*std::exp(-d*d));
}
void lock(IPASoftSimple &af, int target) {
    for (int i=0; i<100; ++i) {
        af.processFocusStats(curve(af.afPosition_, target));
        if (af.afPhase_==IPASoftSimple::AfPhase::Locked) {
            assert(std::abs(af.afPosition_-target)<=32);
            return;
        }
    }
    assert(false);
}
int main() {
    IPASoftSimple af;
    // No lens work before a capture starts.
    for (int i=0; i<100; ++i) assert(!af.processFocusStats(1000));
    af.startFocusScan(); lock(af, 550);
    int original=af.afPosition_, fullScans=0;
    for (int i=0; i<300; ++i) {
        af.processFocusStats(curve(af.afPosition_, 550));
        fullScans += af.afPhase_==IPASoftSimple::AfPhase::Coarse;
    }
    assert(fullScans==0 && std::abs(af.afPosition_-original)<=48);
    // Scene moves nearer, then farther: continuous AF must reacquire.
    for (int target : {800, 240}) {
        bool scanning=false, reacquired=false;
        for (int i=0; i<150; ++i) {
            af.processFocusStats(curve(af.afPosition_, target));
            scanning |= af.afPhase_==IPASoftSimple::AfPhase::Coarse;
            if (scanning && af.afPhase_==IPASoftSimple::AfPhase::Locked) {
                assert(std::abs(af.afPosition_-target)<=32);
                reacquired=true; break;
            }
        }
        assert(reacquired);
    }
    // Single-shot AF must not start continuous probes or scene-change scans.
    af.afMode_=controls::AfModeAuto;
    original=af.afPosition_;
    for (int i=0; i<1000; ++i) assert(!af.processFocusStats(i%2 ? 0 : 20000));
    assert(af.afPosition_==original);
    // Featureless input must not claim successful focus.
    af.startFocusScan();
    for (int i=0; i<100; ++i) af.processFocusStats(0);
    assert(af.afState_==controls::AfStateFailed);
}
'''
with tempfile.TemporaryDirectory(prefix="gts9u-af-test-") as temp:
    binary = str(Path(temp) / "test")
    subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                    "-x", "c++", "-", "-o", binary], input=harness, text=True, check=True)
    subprocess.run([binary], check=True)
print("PASS: initial lock, stable-scene probes, near/far reacquisition, single-shot lock, zero-contrast failure")
