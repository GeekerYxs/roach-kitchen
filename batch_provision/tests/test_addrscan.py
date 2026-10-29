"""Unit tests for provisioner/addrscan.py: PE loading and each signature kind on a tiny synthetic exe, the code /
signature-table agreement, the text check of copies outside provisioner/, and (only where the game is installed)
a scan of the real WAATClient.exe."""
import struct
import tempfile
import unittest
from pathlib import Path

from provisioner import addrscan as a


def fake_exe(text, data=b''):
    """Minimal PE32: headers 0x200, .text at RVA 0x1000, .rdata at RVA 0x2000."""
    sections = [(b'.text', 0x1000, text), (b'.rdata', 0x2000, data)]
    pe = 0x80
    hdr = bytearray(0x200)
    hdr[0:2] = b'MZ'
    struct.pack_into('<I', hdr, 0x3C, pe)
    hdr[pe:pe + 4] = b'PE\0\0'
    struct.pack_into('<HH', hdr, pe + 4, 0x14C, len(sections))
    struct.pack_into('<H', hdr, pe + 20, 0xE0)
    opt = pe + 24
    struct.pack_into('<I', hdr, opt + 28, a.IMAGE_BASE)
    struct.pack_into('<II', hdr, opt + 56, 0x3000, 0x200)
    raw, ptr = bytearray(hdr), 0x200
    for i, (name, rva, body) in enumerate(sections):
        s = opt + 0xE0 + 40 * i
        size = max(len(body), 1)
        raw[s:s + 8] = name.ljust(8, b'\0')
        struct.pack_into('<4I', raw, s + 8, size, rva, size, ptr)
        raw += body.ljust(size, b'\0')
        ptr += size
    return bytes(raw)


class SignatureKinds(unittest.TestCase):
    def setUp(self):
        name_va = a.IMAGE_BASE + 0x2000 + 1
        self.text = (b'\x90' * 0x10 +
                     b'\x55\x8B\xEC\x83\xEC\x10\x8B\x0D' + struct.pack('<I', a.IMAGE_BASE + 0x2345) +   # 0x1010
                     b'\x8B\x81' + struct.pack('<I', 0x12F4) + b'\xC3' +
                     b'\x68' + struct.pack('<I', a.IMAGE_BASE + 0x1010) + b'\x68' + struct.pack('<I', name_va))
        self.data = b'\0CastSkillToFighter\0'
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'WAATClient.exe'
        self.path.write_bytes(fake_exe(self.text, self.data))
        self.image, self.range = a.load_image(self.path)

    def test_image_layout(self):
        self.assertEqual(self.range, (0x1000, 0x1000 + len(self.text)))
        self.assertEqual(self.image[0x1010:0x1013], b'\x55\x8B\xEC')
        self.assertEqual(self.image[0x2001:0x2005], b'Cast')

    def test_func_global_disp_lua(self):
        func = a.Sig('F', a.FUNC, 1, 0, 0, 0, '90 55 8B EC 83 EC 10')
        glob = a.Sig('G', a.GLOBAL, 2, 4, 0, 0, '8B 0D ?? ?? ?? ?? 8B 81')
        disp = a.Sig('D', a.DISP, 2, 4, 0, 0, '8B 81 ?? ?? ?? ?? C3')
        lua = a.Sig('L', a.LUA, 0, 0, 0, 0, 'CastSkillToFighter')
        self.assertEqual(a.resolve(func, self.image, self.range), (0x1010, None))
        self.assertEqual(a.resolve(glob, self.image, self.range), (0x2345, None))
        self.assertEqual(a.resolve(disp, self.image, self.range), (0x12F4, None))
        self.assertEqual(a.resolve(lua, self.image, self.range), (0x1010, None))

    def test_no_match_or_twice_is_not_guessed(self):
        none = a.Sig('N', a.FUNC, 0, 0, 0, 0, 'CC CC CC CC')
        twice = a.Sig('T', a.FUNC, 0, 0, 0, 0, '90 90')
        self.assertIsNone(a.resolve(none, self.image, self.range)[0])
        self.assertIn('0 处', a.resolve(none, self.image, self.range)[1])
        self.assertIsNone(a.resolve(twice, self.image, self.range)[0])

    def test_not_a_pe(self):
        bad = self.path.with_name('bad.exe')
        bad.write_bytes(b'MZ' + b'\0' * 0x100)
        with self.assertRaises(ValueError):
            a.load_image(bad)


class TableAndCode(unittest.TestCase):
    def test_signatures_are_unique_and_parse(self):
        names = [s.name for s in a.SIGS]
        self.assertEqual(len(names), len(set(names)))
        for s in a.SIGS:
            if s.kind != a.LUA:
                a.compile_pattern(s.pattern)
                self.assertLessEqual(s.off + s.size, len(s.pattern.split()), s.name)

    def test_code_uses_the_2101_values(self):
        code = a.code_constants()
        for s in a.SIGS:
            if s.name in code:
                self.assertEqual(code[s.name], s.v2101, s.name)
        for name, (base, delta) in a.DERIVED.items():
            self.assertEqual(code[name], code[base] + delta, name)

    def test_copies_outside_provisioner_agree(self):
        values = {s.name: s.v2101 for s in a.SIGS}
        values.update({n: values[b] + d for n, (b, d) in a.DERIVED.items()})
        self.assertEqual(a.missing_in_files(values), [])

    def test_has_hex(self):
        self.assertTrue(a.has_hex('base+0x6aab34;', 0x6AAB34))
        self.assertTrue(a.has_hex('= 0x6AAB34;', 0x6AAB34))
        self.assertFalse(a.has_hex('0x6AAB340', 0x6AAB34))
        self.assertFalse(a.has_hex('0x16AAB34', 0x6AAB34))

    def test_compare_flags_wrong_and_missing(self):
        rows, problems = a.compare({'A': (1, None), 'B': (None, '特征码匹配 0 处'), 'C': (3, None), 'D': (4, None)},
                                   {'A': 1, 'C': 2})
        self.assertEqual(problems, 2)
        self.assertEqual([r[3] for r in rows][0], '一致')
        self.assertEqual(rows[2][3], '代码里的值不对')
        self.assertEqual(rows[3][3], '只在代码外用')


class RealClient(unittest.TestCase):
    """Runs only where the game is installed (local.toml exe) and it is the 2.101 build."""

    def test_scan_real_exe(self):
        try:
            exe = Path(a.default_exe())
        except Exception:
            self.skipTest('没有 local.toml / supervisor 配置')
        if not exe.is_file():
            self.skipTest('游戏没装在这台电脑')
        from provisioner.doctor import file_sha256
        if file_sha256(exe) != 'ce609262b998d345bedc73b7529c89034f27db9380787278e3fd4226f9fa6100':
            self.skipTest('不是 2.101')
        found = a.scan(exe)
        for s in a.SIGS:
            self.assertEqual(found[s.name][0], s.v2101, s.name)


if __name__ == '__main__':
    unittest.main()
