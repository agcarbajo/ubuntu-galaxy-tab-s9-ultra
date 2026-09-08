#!/usr/bin/env python3
"""Compile the patched releaseContext body against a mock EGL lifecycle."""
from pathlib import Path
import subprocess
import sys
import tempfile

source = Path(sys.argv[1]).read_text()
start = source.index("void eGL::releaseContext()")
end = source.index("\n}", start) + 2
body = source[start:end]
harness = r'''
#include <cassert>
#include <vector>
constexpr int EGL_NO_CONTEXT=0, EGL_NO_SURFACE=0;
int current=0, destroyed=0, surfaces=0;
std::vector<int> events;
int eglGetCurrentContext() { return current; }
int eglMakeCurrent(int, int, int, int context) {
    current=context; events.push_back(1); return 1;
}
int eglDestroyContext(int, int context) {
    assert(current != context); ++destroyed; events.push_back(2); return 1;
}
int eglDestroySurface(int, int) { ++surfaces; return 1; }
struct eGL {
    int display_=1, context_=0, surface_=0;
    void releaseContext();
};
''' + body + r'''
int main() {
    eGL egl;
    for (int i=1; i<=100; ++i) {
        egl.context_=i; current=i; events.clear();
        egl.releaseContext();
        assert(current==0 && egl.context_==0);
        assert((events==std::vector<int>{1,2}));
        egl.releaseContext();
        assert(destroyed==i);
    }
    current=999; egl.context_=101; egl.surface_=5;
    events.clear(); egl.releaseContext(); egl.releaseContext();
    assert(current==999 && destroyed==101 && surfaces==1);
    assert((events==std::vector<int>{2}));
}
'''
with tempfile.TemporaryDirectory(prefix="gts9u-egl-test-") as temp:
    binary = str(Path(temp) / "test")
    subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                    "-x", "c++", "-", "-o", binary], input=harness, text=True, check=True)
    subprocess.run([binary], check=True)
print("PASS: 100 release/reopen lifetimes, idempotence, detach-before-destroy, foreign context preserved")
