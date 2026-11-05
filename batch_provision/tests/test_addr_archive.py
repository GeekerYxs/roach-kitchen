"""provisioner.addrscan's per-version archive (user 2026-11-05): numbers only (the repo is public, no game exe in it),
so a new PC without the old exe still knows every address of earlier versions."""
import json
import struct
import tempfile
import unittest
from pathlib import Path

from provisioner import addrscan as a


class ExeInfo(unittest.TestCase):
    def test_version_size_hash_stamp(self):
        raw = bytearray(0x400)
        raw[0:2] = b'MZ'
        struct.pack_into('<I', raw, 0x3C, 0x80)
        raw[0x80:0x84] = b'PE\0\0'
        struct.pack_into('<I', raw, 0x88, 0x6AE0AF0A)
        i = 0x300
        raw[i:i + 4] = b'\xbd\x04\xef\xfe'
        struct.pack_into('<II', raw, i + 8, (2 << 16) | 101, (2643 << 16) | 6157)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'WAATClient.exe'
            p.write_bytes(bytes(raw))
            info = a.exe_info(p)
        self.assertEqual((info['version'], info['size'], info['pe_timestamp']), ('2.101.2643.6157', 0x400, '0x6ae0af0a'))
        self.assertEqual(len(info['sha256']), 64)


class Archive(unittest.TestCase):
    def test_save_load_history(self):
        with tempfile.TemporaryDirectory() as d:
            for ver, ui in (('2.100.1.1', 0x10), ('2.101.1.1', 0x20)):
                rec = a.archive_record({'version': ver, 'size': 1, 'sha256': 'x', 'pe_timestamp': '0x1'},
                                       {'UI': (ui, None), 'SEND': (0x5, None), 'LOST': (None, 'no')}, 'test')
                a.save_archive(rec, d)
            recs = a.load_archives(d)
            self.assertEqual([r['version'] for r in recs], ['2.100.1.1', '2.101.1.1'])
            self.assertEqual(recs[1]['missing'], ['LOST'])
            lines = a.history(folder=d)
            self.assertTrue(any(l.startswith('UI') and '0x10' in l and '0x20' in l for l in lines))
            self.assertFalse(any(l.startswith('SEND') for l in lines))          # unchanged: only when asked for
            self.assertTrue(any(l.startswith('SEND') for l in a.history(['SEND'], folder=d)))

    def test_current_version_archive_matches_the_code(self):
        """The archive of the version the code is written for must hold the code's numbers."""
        recs = {r['version']: r for r in a.load_archives()}
        cur = recs['2.101.2643.6157']
        self.assertEqual(cur['sha256'], 'ce609262b998d345bedc73b7529c89034f27db9380787278e3fd4226f9fa6100')
        code = a.code_constants()
        for name, hexv in cur['addresses'].items():
            if name in code:
                self.assertEqual(int(hexv, 16), code[name], name)
        self.assertIn('2.100.2642.6130', recs)

    def test_no_exe_in_the_archive_folder(self):
        self.assertEqual([p.name for p in a.ARCHIVE.iterdir() if p.suffix.lower() != '.json'], [])


if __name__ == '__main__':
    unittest.main()
