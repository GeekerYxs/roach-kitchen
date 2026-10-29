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

    def test_repo_launcher_accepts_2101_only(self):
        """2.101 moved every address again: older builds (2.100 bc7d6c22...) must be refused, not run with wrong
        addresses."""
        known = doctor.expected_client_hashes()
        self.assertEqual({'ce609262b998d345bedc73b7529c89034f27db9380787278e3fd4226f9fa6100': '2.101'}, known)


if __name__ == '__main__':
    unittest.main()
