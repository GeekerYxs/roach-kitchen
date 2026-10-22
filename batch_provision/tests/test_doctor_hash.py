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

    def test_repo_launcher_accepts_2100_only(self):
        """2.100 moved every address: the old builds must be refused, not run with wrong addresses."""
        known = doctor.expected_client_hashes()
        self.assertEqual({'bc7d6c22aea54f14d2e4715ac99994bee5158dbb4e8d1a608d632183d377b5ec': '2.100'}, known)


if __name__ == '__main__':
    unittest.main()
