#!/usr/bin/env python3
import re
from pathlib import Path
import subprocess
import sys
import tempfile

repo = Path(__file__).resolve().parents[1]
original = Path(sys.argv[1]).read_text()


def function(source, name):
    match = re.search(rf'^static [^;]*\b{name}\([^;]*\)\n\{{', source, re.M)
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


with tempfile.TemporaryDirectory(prefix='gts9u-bridge-oob-test-') as tmp:
    tree = Path(tmp)
    source = tree / 'drivers/gpu/drm/display/drm_bridge_connector.c'
    source.parent.mkdir(parents=True)
    source.write_text(original)
    subprocess.run(['git', 'init', '-q', tmp], check=True)
    patch = repo / 'kernel/patches/drm-bridge-oob-ignore-unchanged-status.patch'
    subprocess.run(['git', '-C', tmp, 'apply', str(patch)], check=True)
    patched = source.read_text()
    helper = function(patched, 'drm_bridge_connector_should_send_hotplug')
    harness = r'''
#include <assert.h>
#include <stdbool.h>
enum drm_connector_status {
  connector_status_unknown,
  connector_status_connected,
  connector_status_disconnected
};
'''
    harness += helper
    harness += r'''
int main(void) {
  assert(!drm_bridge_connector_should_send_hotplug(connector_status_connected,
                                                    connector_status_connected,
                                                    false));
  assert(drm_bridge_connector_should_send_hotplug(connector_status_connected,
                                                   connector_status_connected,
                                                   true));
  assert(drm_bridge_connector_should_send_hotplug(connector_status_disconnected,
                                                   connector_status_connected,
                                                   false));
  assert(drm_bridge_connector_should_send_hotplug(connector_status_connected,
                                                   connector_status_disconnected,
                                                   false));
}
'''
    test = tree / 'hotplug-test.c'
    test.write_text(harness)
    exe = tree / 'hotplug-test'
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', str(test), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
    assert 'drm_bridge_connector_handle_hpd(cb_data, status, true);' in patched
    assert 'drm_bridge_connector_handle_hpd(bridge_connector, status, false);' in patched
    print('PASS: OOB same-status hotplug suppressed; callbacks and real transitions preserved')
