#!/usr/bin/env python3
import re
from pathlib import Path
import subprocess
import sys
import tempfile

repo = Path(__file__).resolve().parents[1]
original = Path(sys.argv[1]).read_text()


def function(source, name):
    match = re.search(rf'^static [^;]*\n{name} \([^;]*\)\n\{{', source, re.M)
    assert match, f'{name} not found'
    brace = source.index('{', match.start())
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == '{':
            depth += 1
        elif source[index] == '}':
            depth -= 1
            if depth == 0:
                return source[match.start():index + 1]
    raise AssertionError(f'{name} is incomplete')


with tempfile.TemporaryDirectory(prefix='gts9u-mutter-plane-test-') as tmp:
    tree = Path(tmp)
    source = tree / 'src/backends/native/meta-crtc-kms.c'
    source.parent.mkdir(parents=True)
    source.write_text(original)
    patch = repo / 'packaging/mutter/preserve-crtc-plane-assignments.patch'
    subprocess.run(['patch', '--batch', '--fuzz=0', '-d', tmp, '-p1'],
                   input=patch.read_text(), text=True, check=True)
    patched = source.read_text()
    get_assigned = function(patched, 'get_assigned_plane')
    find_unassigned = function(patched, 'find_unassigned_plane')
    harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>
typedef enum { META_KMS_PLANE_TYPE_PRIMARY, META_KMS_PLANE_TYPE_CURSOR,
               META_KMS_PLANE_TYPE_OVERLAY } MetaKmsPlaneType;
typedef struct Plane MetaKmsPlane;
typedef struct List { void *data; struct List *next; } GList;
typedef struct Device { GList *planes; } MetaKmsDevice;
typedef struct Crtc { MetaKmsDevice *device; } MetaKmsCrtc;
typedef struct CRTC { MetaKmsCrtc *kms_crtc; MetaKmsPlane *assigned_primary_plane;
                      MetaKmsPlane *assigned_cursor_plane; } MetaCrtcKms;
typedef struct { int unused; } GPtrArray;
struct Plane { MetaKmsPlaneType type; bool usable; bool claimed; int id; };
#define g_assert_not_reached() abort()
static MetaKmsCrtc *meta_crtc_kms_get_kms_crtc(MetaCrtcKms *c) { return c->kms_crtc; }
static MetaKmsDevice *meta_kms_crtc_get_device(MetaKmsCrtc *c) { return c->device; }
static GList *meta_kms_device_get_planes(MetaKmsDevice *d) { return d->planes; }
static MetaKmsPlaneType meta_kms_plane_get_plane_type(MetaKmsPlane *p) { return p->type; }
static bool meta_kms_plane_is_usable_with(MetaKmsPlane *p, MetaKmsCrtc *c) { (void)c; return p->usable; }
static bool is_plane_assigned(MetaKmsPlane *p, MetaKmsPlaneType t, GPtrArray *a) {
  (void)t; (void)a; return p->claimed;
}
'''
    harness += get_assigned + '\n' + find_unassigned
    harness += r'''
int main(void) {
  MetaKmsPlane old = {META_KMS_PLANE_TYPE_PRIMARY, true, false, 0};
  MetaKmsPlane first = {META_KMS_PLANE_TYPE_PRIMARY, true, false, 1};
  MetaKmsPlane cursor = {META_KMS_PLANE_TYPE_CURSOR, true, false, 2};
  GList l2 = {&old, NULL}, l1 = {&first, &l2}, l0 = {&cursor, &l1};
  MetaKmsDevice device = {&l0}; MetaKmsCrtc kms_crtc = {&device};
  MetaCrtcKms crtc = {&kms_crtc, &old, &cursor}; GPtrArray assignments = {0};
  assert(find_unassigned_plane(&crtc, META_KMS_PLANE_TYPE_PRIMARY, &assignments) == &old);
  old.claimed = true;
  assert(find_unassigned_plane(&crtc, META_KMS_PLANE_TYPE_PRIMARY, &assignments) == &first);
  old.claimed = false; old.usable = false;
  assert(find_unassigned_plane(&crtc, META_KMS_PLANE_TYPE_PRIMARY, &assignments) == &first);
  old.usable = true; crtc.assigned_primary_plane = NULL;
  assert(find_unassigned_plane(&crtc, META_KMS_PLANE_TYPE_PRIMARY, &assignments) == &first);
  assert(find_unassigned_plane(&crtc, META_KMS_PLANE_TYPE_CURSOR, &assignments) == &cursor);
}
'''
    test = tree / 'plane-test.c'
    test.write_text(harness)
    exe = tree / 'plane-test'
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', str(test), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
    print('PASS: existing compatible CRTC planes survive reordered monitor assignments')
