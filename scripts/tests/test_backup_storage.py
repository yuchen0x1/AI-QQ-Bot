"""Failed dumps/compression must not publish a backup or prune older ones."""

from __future__ import annotations

import gzip
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backup_storage import finalize, verify

ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash") or ("C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else None)


class BackupStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old = self.root / "qbot-older.sql.gz"
        self.old.write_bytes(gzip.compress(b"old valid dump"))

    def test_valid_backup_published_with_checksum_before_retention(self):
        temporary = self.root / ".pending"
        temporary.write_bytes(gzip.compress(b"-- PostgreSQL database dump\nSELECT 1;"))
        target = self.root / "qbot-new.sql.gz"
        finalize(temporary, target, keep=1)
        self.assertFalse(temporary.exists())
        self.assertFalse(self.old.exists())
        self.assertTrue(target.with_name(target.name + ".sha256").is_file())
        verify(target)

    def test_empty_truncated_or_invalid_dump_never_prunes(self):
        for content in (gzip.compress(b""), gzip.compress(b"dump")[:-3], b"not gzip"):
            with self.subTest(content=content):
                temporary = self.root / ".pending"
                temporary.write_bytes(content)
                target = self.root / "qbot-new.sql.gz"
                with self.assertRaises((ValueError, OSError, EOFError)):
                    finalize(temporary, target, keep=1)
                self.assertTrue(self.old.exists())
                self.assertFalse(target.exists())

    def test_tampered_dump_is_rejected_before_restore(self):
        temporary = self.root / ".pending"
        temporary.write_bytes(gzip.compress(b"original"))
        target = self.root / "qbot-new.sql.gz"
        finalize(temporary, target)
        target.write_bytes(gzip.compress(b"changed"))
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            verify(target)

    @unittest.skipUnless(BASH and Path(BASH).is_file(), "Bash is not installed")
    def test_failed_pg_dump_in_actual_shell_script_preserves_old_backups(self):
        shutil.copy2(ROOT / "backup.sh", self.root / "backup.sh")
        (self.root / ".env").touch()
        backups = self.root / "backups"
        backups.mkdir()
        for index in range(16):
            (backups / f"qbot-old-{index}.sql.gz").write_bytes(gzip.compress(b"old dump"))
        binary = self.root / "bin"
        binary.mkdir()
        docker = binary / "docker"
        docker.write_text("#!/usr/bin/env bash\nprintf 'partial dump'\nexit 17\n", encoding="utf-8", newline="\n")
        docker.chmod(0o755)
        result = subprocess.run([str(BASH), "backup.sh"], cwd=self.root, check=False,
                                env={**os.environ, "PATH": f"{binary}{os.pathsep}{os.environ.get('PATH', '')}"},
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(len(list(backups.glob("qbot-*.sql.gz"))), 16)
        self.assertEqual(list(backups.glob(".qbot-backup-*")), [])


if __name__ == "__main__":
    unittest.main()
