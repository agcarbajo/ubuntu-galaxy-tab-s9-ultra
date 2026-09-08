#!/usr/bin/env python3
"""Compile the production line-statistics macros against synthetic luminance.

Checks noise filtering and unchanged colour/exposure statistics; not optical QA.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

s = Path(sys.argv[1]).read_text()
macros = s[s.index('#define SWSTATS_START_LINE_STATS'):s.index('void SwStatsCpu::statsBGGR8Line0')]
harness = r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <vector>
constexpr unsigned kRedYMul=77, kGreenYMul=150, kBlueYMul=29;
struct RGB { uint64_t red=0, green=0, blue=0;
uint64_t &r(){return red;} uint64_t &g(){return green;} uint64_t &b(){return blue;}};
struct SwIspStats { static constexpr unsigned kYHistogramSize=64;
RGB sum_; uint64_t focus=0, luminance=0, focusSamples=0;
std::array<uint64_t,kYHistogramSize> yHistogram{}; };
''' + macros + r'''
SwIspStats measure(const std::vector<uint8_t> &values) {
    SwIspStats stats;
    SWSTATS_START_LINE_STATS(uint8_t)
    for (auto value : values) {
        r=b=g2=value; g=(r+g2)/2;
        SWSTATS_ACCUMULATE_LINE_STATS(1)
    }
    SWSTATS_FINISH_LINE_STATS()
    return stats;
}
int main() {
    std::vector<uint8_t> blank(512,30), noise(512), sharp(512), blurred(512);
    uint32_t rng=1;
    for (unsigned i=0;i<512;++i) {
        rng=1664525*rng+1013904223;
        noise[i]=30+int((rng>>16)%21)-10;
        sharp[i]=(i/32)%2 ? 80 : 20;
    }
    for (int i=0;i<512;++i) {
        unsigned sum=0;
        for (int j=-8;j<=8;++j) {
            int index=i+j; if(index<0) index=0; if(index>511) index=511;
            sum+=sharp[index];
        }
        blurred[i]=sum/17;
    }
    assert(measure(blank).focus==0);
    auto n=measure(noise); uint64_t original=0, sum=0;
    std::array<uint64_t,64> histogram{};
    for (unsigned i=0;i<noise.size();++i) {
        sum+=noise[i]; histogram[noise[i]/4]++;
        if(i>=2) original+=std::abs(int(noise[i-2])-2*int(noise[i-1])+int(noise[i]));
    }
    assert(n.focus*4<original);
    assert(n.luminance==sum && n.focusSamples==noise.size());
    assert(n.sum_.red==sum && n.sum_.green==sum && n.sum_.blue==sum);
    assert(n.yHistogram==histogram);
    assert(measure(sharp).focus>measure(blurred).focus*1.2);
}
'''
with tempfile.TemporaryDirectory(prefix='gts9u-focus-metric-') as d:
    binary = str(Path(d)/'test')
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-x','c++','-',
                    '-o',binary],input=harness,text=True,check=True)
    subprocess.run([binary],check=True)
print('PASS: flat scene, noise filtering, sharp/blurred separation, unchanged RGB/luminance/histogram')
