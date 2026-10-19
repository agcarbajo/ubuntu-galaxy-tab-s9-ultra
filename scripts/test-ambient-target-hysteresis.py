#!/usr/bin/env python3
"""Compile the GNOME 50 callback and exercise noise, lighting and reset paths."""
import pathlib
import subprocess
import sys
import tempfile

source = pathlib.Path(sys.argv[1]).read_text()
start = source.index('static void\niio_proxy_changed (')
end = source.index('\nstatic void\niio_proxy_changed_cb', start)
fixture = r'''
#include <glib.h>
#include <math.h>
#include <string.h>
#include <assert.h>
typedef struct {
 void *settings, *iio_proxy;
 gboolean ambient_norm_required;
 double ambient_accumulator, ambient_norm_value, ambient_target_last;
 gint64 ambient_update_last_time, ambient_set_last_time;
} GsdPowerManager;
static gboolean enabled=TRUE, control=TRUE, has_light=TRUE;
static double lux=84, target=-1;
static gint64 clock_us=10000000;
static int writes=0;
static gint64 fake_time(void) { return clock_us; }
static gboolean fake_enabled(void *p,const char *k) { return enabled; }
static gboolean shell_brightness_has_control(GsdPowerManager *m) { return control; }
static GVariant *fake_property(void *p,const char *k) {
 return g_variant_ref_sink(strcmp(k,"HasAmbientLight")==0 ? g_variant_new_boolean(has_light) : g_variant_new_double(lux));
}
static void shell_brightness_set_auto_target(GsdPowerManager *m,double v) { target=v; writes++; }
#define g_get_monotonic_time fake_time
#define g_settings_get_boolean fake_enabled
#define g_dbus_proxy_get_cached_property fake_property
#define GSD_AMBIENT_TIME_CONSTANT (1e6 / (2 * G_PI * 0.1))
#define GSD_AMBIENT_SEND_UPDATE_INTERVAL (1e6 * 0.1)
#define GSD_AMBIENT_NORMALIZE_CONSTANT 1.5
'''
main = r'''
static void sample(GsdPowerManager *m,double light) {
 lux=light;clock_us+=1000000;iio_proxy_changed(m);
}
int main(void) {
 GsdPowerManager m={.ambient_norm_required=TRUE,.ambient_accumulator=-1};
 sample(&m,84);assert(writes==1);double initial=target;
 /* Observed stable-room lux range, including alternate positive/negative noise. */
 double noise[]={84,82,86,81,85,83,87,82,84,90,81,83,85,82,86,84};
 for(int i=0;i<160;i++) sample(&m,noise[i%G_N_ELEMENTS(noise)]);
 assert(writes<=3);assert(fabs(target-initial)<0.06);
 assert(m.ambient_update_last_time==clock_us);
 /* A dark step and bright step must both settle within ten seconds. */
 for(int i=0;i<10;i++) sample(&m,20);
 assert(target<0.20);int before=writes;
 for(int i=0;i<10;i++) sample(&m,180);
 assert(target>0.95);assert(writes>before);
 /* Slow accumulated changes must escape the dead band. */
 for(int i=0;i<30;i++) sample(&m,50);
 double low=target;
 for(int i=0;i<60;i++) sample(&m,50+i*0.5);
 assert(target>low+0.15);
 /* Manual adjustment/dimming normalization must send even the same target. */
 before=writes;m.ambient_norm_required=TRUE;sample(&m,lux);assert(writes==before+1);
 before=writes;m.ambient_set_last_time=0;sample(&m,lux);assert(writes==before+1);
 /* Disabled, unavailable hardware and invalid readings must remain inert. */
 before=writes;enabled=FALSE;sample(&m,80);enabled=TRUE;
 control=FALSE;sample(&m,80);control=TRUE;
 has_light=FALSE;sample(&m,80);has_light=TRUE;
 sample(&m,0);assert(writes==before);
 g_print("PASS: stable-room noise, dark/bright steps, slow drift, resets and disabled paths\n");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = pathlib.Path(tmp)
    (path / 'test.c').write_text(fixture + source[start:end] + main)
    flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'glib-2.0'], text=True).split()
    subprocess.run(['cc', '-Werror', str(path / 'test.c'), '-o', str(path / 'test'), *flags, '-lm'], check=True)
    subprocess.run([str(path / 'test')], check=True)
