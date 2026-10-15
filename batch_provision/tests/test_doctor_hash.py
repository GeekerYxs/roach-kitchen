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
            src.write_text(f'static const char* CLIENT_HASH="{want}";\n', 'utf-8')
            self.assertEqual(doctor.expected_client_hash(src), want)
            self.assertEqual(doctor.file_sha256(exe), want)

    def test_missing_source_gives_none(self):
        self.assertIsNone(doctor.expected_client_hash(Path(tempfile.gettempdir()) / 'no_such_launcher.cpp'))

    def test_repo_launcher_hash_is_present(self):
        self.assertRegex(doctor.expected_client_hash() or '', r'^[0-9a-f]{64}$')


if __name__ == '__main__':
    unittest.main()
