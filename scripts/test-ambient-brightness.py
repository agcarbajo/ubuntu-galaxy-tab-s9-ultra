#!/usr/bin/env python3
"""Compile and exercise the real patched ambient callback with fake I/O."""
import pathlib,subprocess,sys,tempfile
source=pathlib.Path(sys.argv[1]).read_text()
a=source.index('static void\niio_proxy_changed (');b=source.index('\nstatic void\niio_proxy_changed_cb',a)
callback=source[a:b]
fixture=r'''
#include <glib.h>
#include <string.h>
#include <assert.h>
typedef struct {
 void *backlight, *settings, *iio_proxy;
 double ambient_last_absolute, ambient_accumulator, ambient_norm_value, ambient_percentage_old;
 gboolean ambient_norm_required;
 gint64 ambient_last_time;
} GsdPowerManager;
static int actual=50, writes=0;
static gboolean enabled=TRUE;
static double lux=50;
static gint64 clock_us=10000000;
static gint64 fake_time(void) { return clock_us; }
static gboolean fake_enabled(void *p,const char *k) { return enabled; }
static GVariant *fake_property(void *p,const char *k) {
 return g_variant_ref_sink(strcmp(k,"HasAmbientLight")==0 ? g_variant_new_boolean(TRUE) : g_variant_new_double(lux));
}
static int gsd_backlight_get_brightness(void *p,void *t) { return actual; }
static void gsd_backlight_set_brightness_async(void *p,int pc,void *c,void *cb,void *u) { actual=pc; writes++; }
static void ch_backlight_renormalize(GsdPowerManager *m) { assert(!"unexpected renormalization"); }
#define g_get_monotonic_time fake_time
#define g_settings_get_boolean fake_enabled
#define g_dbus_proxy_get_cached_property fake_property
#define GSD_AMBIENT_TIME_CONSTANT 1000000.0
'''
main=r'''
int main(void) {
 GsdPowerManager m={.backlight=(void*)1,.ambient_accumulator=50,.ambient_norm_value=100,.ambient_percentage_old=50,.ambient_last_time=9000000};
 for(int i=0;i<100;i++){clock_us+=100000;iio_proxy_changed(&m);}
 assert(writes==0);assert(m.ambient_last_time==clock_us);
 lux=90;clock_us+=1000000;iio_proxy_changed(&m);
 assert(writes==1);assert(actual>50 && actual<90);assert(m.ambient_accumulator>50);
 /* Observed external/manual/dim state differs, despite unchanged last target. */
 lux=m.ambient_accumulator;actual=10;clock_us+=1000000;iio_proxy_changed(&m);
 assert(writes==2);assert(actual>50);
 enabled=FALSE;lux=20;clock_us+=1000000;iio_proxy_changed(&m);assert(writes==2);
 g_print("PASS: 100 identical targets skipped, smoothing advances, changes and external state still applied\n");
}
'''
with tempfile.TemporaryDirectory() as tmp:
 path=pathlib.Path(tmp);(path/'test.c').write_text(fixture+callback+main)
 flags=subprocess.check_output(['pkg-config','--cflags','--libs','glib-2.0'],text=True).split()
 subprocess.run(['cc','-Werror','-Wno-unused-function',str(path/'test.c'),'-o',str(path/'test'),*flags],check=True)
 subprocess.run([str(path/'test')],check=True)