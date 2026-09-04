#!/usr/bin/env python3
"""Execute the actual driver packet handler with fake input sinks and sanitizers."""
from pathlib import Path
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[1] / "kernel/drivers/samsung_stm32_pogo.c").read_text(encoding="utf-8")
start = source.index("static void samsung_pogo_report_touchpad(")
end = source.index("\nstatic ", start + 1)
handler = source[start:end]
shim = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
typedef uint8_t u8;
typedef uint16_t u16;
#define BIT(n) (1U << (n))
#define MT_TOOL_FINGER 0
#define BTN_LEFT 1
#define ABS_MT_POSITION_X 2
#define ABS_MT_POSITION_Y 3
#define ABS_MT_TOUCH_MAJOR 4
struct input_dev { int slot, active[3], x[3], y[3], width[3], button, syncs; };
struct samsung_pogo { struct input_dev *touchpad; u16 touchpad_max_x, touchpad_max_y;
    long touchpad_packets, touchpad_bad_packets; };
static u16 get_unaligned_le16(const u8 *p) { return p[0] | p[1] << 8; }
static void atomic64_inc(long *v) { ++*v; }
static void input_mt_slot(struct input_dev *d, int s) { assert(s>=0 && s<3); d->slot=s; }
static void input_mt_report_slot_state(struct input_dev *d, int tool, bool active) { d->active[d->slot]=active; }
static void input_report_key(struct input_dev *d, int code, int value) { d->button=!!value; }
static void input_report_abs(struct input_dev *d, int code, int value) {
    if(code==ABS_MT_POSITION_X) d->x[d->slot]=value;
    if(code==ABS_MT_POSITION_Y) d->y[d->slot]=value;
    if(code==ABS_MT_TOUCH_MAJOR) d->width[d->slot]=value;
}
static void input_mt_sync_frame(struct input_dev *d) {}
static void input_sync(struct input_dev *d) { d->syncs++; }
static void samsung_pogo_release_touchpad(struct samsung_pogo *p) {
    memset(p->touchpad->active,0,sizeof(p->touchpad->active));p->touchpad->button=0;
}
#define dev_warn_ratelimited(...) ((void)0)
'''
tests = r'''
int main(void) {
    struct input_dev d={0}; struct samsung_pogo p={.touchpad=&d,.touchpad_max_x=1764,.touchpad_max_y=1072};
    u8 packet[23]={0};
    /* Three contacts, plus a physical click. */
    packet[1]=0x88;packet[2]=3;packet[3]=1;
    for(int i=0;i<3;i++) {packet[4+6*i]=100+i;packet[6+6*i]=50+i;packet[8+6*i]=20;packet[9+6*i]=1;}
    samsung_pogo_report_touchpad(&p,packet,22);
    for(int i=0;i<3;i++) {assert(d.active[i]);assert(d.x[i]==100+i);assert(d.y[i]==50+i);}
    assert(d.button && p.touchpad_packets==1 && p.touchpad_bad_packets==0);
    /* Lifting one finger must not release the others; no button event preserves click. */
    packet[1]=0x08;packet[2]=2;packet[9]=0;
    samsung_pogo_report_touchpad(&p,packet,22);assert(!d.active[0] && d.active[1] && d.active[2] && d.button);
    memset(packet,0,sizeof(packet));packet[1]=0x80;
    samsung_pogo_report_touchpad(&p,packet,22);assert(!d.button && !d.active[1] && !d.active[2]);
    /* Invalid length/count/coordinate frames release state and never access out of bounds. */
    samsung_pogo_report_touchpad(&p,NULL,0);
    samsung_pogo_report_touchpad(&p,packet,21);
    samsung_pogo_report_touchpad(&p,packet,23);
    packet[2]=4;samsung_pogo_report_touchpad(&p,packet,22);
    packet[2]=1;packet[1]=0x08;packet[9]=1;packet[4]=0xe4;packet[5]=6; /* x=1764, just out of range */
    samsung_pogo_report_touchpad(&p,packet,22);assert(p.touchpad_bad_packets==5);
    packet[4]=0xe3;packet[6]=0x2f;packet[7]=4; /* x=1763, y=1071: valid upper bounds */
    samsung_pogo_report_touchpad(&p,packet,22);assert(d.active[0] && d.x[0]==1763 && d.y[0]==1071);
    packet[6]=0x30;samsung_pogo_report_touchpad(&p,packet,22);assert(!d.active[0] && p.touchpad_bad_packets==6);
    p.touchpad=NULL;samsung_pogo_report_touchpad(&p,NULL,0);
    return 0;
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "pogo.c"
    path.write_text(shim + handler + tests, encoding="utf-8")
    executable = Path(tmp) / "pogo-test"
    subprocess.run(["cc", "-std=c11", "-fsanitize=address,undefined", "-g", str(path), "-o", str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
print("PASS actual touchpad handler: contacts, release, click, bounds and malformed frames")
