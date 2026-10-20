import hashlib
import tempfile
import unittest
from pathlib import Path

from provisioner import doctor


class ClientHashTest(unittest.TestCase):
    def test_reads_launcher_hash_and_matches_file(self):
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / 'game.exe'
            exe.write_bytes(b'game build')
            want = hashlib.sha256(b'game build').hexdigest()
            src = Path(d) / 'launcher.cpp'
            src.write_text('static const char* CLIENT_HASHES[]={\n'
                           f'    "{"0" * 64}", // 2.98\n    "{want}", // 2.99\n}};\n', 'utf-8')
            self.assertEqual({'0' * 64: '2.98', want: '2.99'}, doctor.expected_client_hashes(src))
            self.assertEqual(doctor.file_sha256(exe), want)

    def test_missing_source_gives_nothing(self):
        self.assertEqual({}, doctor.expected_client_hashes(Path(tempfile.gettempdir()) / 'no_such_launcher.cpp'))

    def test_repo_launcher_accepts_298_and_299(self):
        known = doctor.expected_client_hashes()
        self.assertEqual('2.98', known.get('500cf8f165cfbbf6f8f28ddb01648dbee3de10a1a8068f51b359598560958c27'))
        self.assertEqual('2.99', known.get('c33ff869a1e54ef354d5e7d65a235879c2301a1f1890f6c88105d8ebd7eded86'))


if __name__ == '__main__':
    unittest.main()
