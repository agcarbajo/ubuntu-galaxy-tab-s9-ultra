#!/usr/bin/env python3
"""Offline release Markdown and public system summary fixtures."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import gi
gi.require_version("Pango", "1.0")
from gi.repository import Pango

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                      "packaging/ubuntu-gts9u-companion/usr/lib/tab-companion"))
from tab_companion import release_markdown as md, system_summary as summary, update_bundle as bundle


class BuildInfoTests(unittest.TestCase):
    def parse(self, source):
        value = md.markup(source)
        # Gtk.Label links are consumed by GTK, before Pango handles styling.
        import re
        pango = re.sub(r'</?a\b[^>]*>', '', value)
        self.assertTrue(Pango.parse_markup(pango, -1, '\0')[0])
        return value

    def test_markdown_blocks_inline_and_nested_lists(self):
        value = self.parse('# New build\n\n**Bold** and *italic* with `x < y`.\n\n3. First\n4. Second\n   - Nested\n\n> Quote\n\n```sh\necho "<&>"\n```\n\n~~old~~')
        for expected in ('weight="bold"', '<b>Bold</b>', '<i>italic</i>', '<tt>x &lt; y</tt>',
                         '3. First', '4. Second', '  • Nested', '<s>old</s>', '&lt;&amp;&gt;'):
            self.assertIn(expected, value)

    def test_links_and_untrusted_html(self):
        value = self.parse('[GitHub](https://github.com/a?x=1&y=2)\n\n<script>bad()</script>\n\n[local](file:///etc/passwd)\n\n![Alt](https://example.com/image.png)\n<!-- hidden -->')
        self.assertIn('href="https://github.com/a?x=1&amp;y=2"', value)
        self.assertNotIn('href="file:', value)
        self.assertNotIn('<script>', value)
        self.assertNotIn('hidden', value)
        self.assertIn('Alt', value)
        self.assertNotIn('image.png', value)

    def test_table_unicode_and_empty(self):
        self.assertIn('<b>Kernel</b>', self.parse('| Kernel | Ubuntu |\n| --- | --- |\n| 7.2 | 26.04 |'))
        self.assertIn('á &amp; β', self.parse('á & β'))
        self.assertEqual(md.markup(''), '')

    def test_summary_uses_installed_identity_and_actual_ram_uptime(self):
        values = {'/etc/os-release': 'PRETTY_NAME="Ubuntu 24.04.5 LTS"',
                  '/proc/device-tree/compatible': 'samsung,gts9uwifi\0qcom,sm8550\0',
                  '/proc/meminfo': 'MemTotal:       12582912 kB', '/proc/uptime': '90061.4 180000.0',
                  '/proc/cpuinfo': ''}
        with patch.object(summary, 'read', side_effect=lambda path: values.get(path, '')), \
             patch.object(summary.update_bundle, 'current', return_value={'tag':'v1.2.0'}), \
             patch.object(summary, '_', side_effect=lambda text:text):
            result = dict(summary.rows())
        self.assertEqual(result['Port version'], 'v1.2.0')
        self.assertEqual(result['Ubuntu'], 'Ubuntu 24.04.5 LTS')
        self.assertEqual(result['RAM'], '12.0 GiB usable')
        self.assertEqual(result['Uptime'], '1 d · 1 h · 1 min')
        self.assertIn('SM8550', result['Processor'])
        self.assertTrue(result['Kernel'])

    def test_missing_system_data_and_escaped_markup(self):
        with patch.object(summary, 'read', return_value=''), patch.object(summary.update_bundle, 'current', return_value={}):
            result = summary.rows()
        self.assertEqual(len(result), 6)
        value = summary.markup([('Title', '<fake>&')])
        self.assertIn('&lt;fake&gt;&amp;', value)
        self.assertTrue(Pango.parse_markup(value, -1, '\0')[0])

    def test_installed_notes_do_not_require_retained_assets(self):
        import io, json
        stream = io.BytesIO(json.dumps({'tag_name':'v1.2.0', 'body':'## Installed\n<!-- marker -->\n**Fix**', 'assets':[]}).encode())
        with patch.object(bundle, 'request', return_value=stream) as request:
            self.assertEqual(bundle.release_notes('v1.2.0'), '## Installed\n\n**Fix**')
            self.assertTrue(request.call_args.args[0].endswith('/tags/v1.2.0'))

    def test_installed_notes_reject_different_tag(self):
        import io, json
        with patch.object(bundle, 'request', return_value=io.BytesIO(json.dumps({'tag_name':'v9.0.0'}).encode())):
            with self.assertRaises(ValueError):
                bundle.release_notes('v1.2.0')


if __name__ == '__main__':
    unittest.main()
