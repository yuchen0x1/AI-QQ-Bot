"""Exercise actual Bash restore ordering with a controlled Docker CLI transport."""

from __future__ import annotations

import gzip
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash") or ("C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else None)


@unittest.skipUnless(BASH and Path(BASH).is_file(), "Bash is not installed")
class RestoreWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for source in ("backup.sh", "restore.sh", "scripts/backup_storage.py", "backend/migrations/versions/0015_ws_tickets.py"):
            target = self.root / source
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / source, target)
        (self.root / ".env").touch()
        self.archive = self.root / "input.sql.gz"
        self.archive.write_bytes(gzip.compress(b"-- PostgreSQL database dump\nSELECT 1;\n"))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "docker.log"
        self.write_command("python3", f'#!/usr/bin/env bash\nexec "{Path(sys.executable).as_posix()}" "$@"\n')
        self.write_command("docker", '''#!/usr/bin/env bash
printf '%s\\t' "$@" >> "$QBOT_TEST_LOG"
printf '\\n' >> "$QBOT_TEST_LOG"
joined="$*"
if [[ "$joined" == *"ps --services --status running"* ]]; then printf 'backend\\nworker\\n'; exit 0; fi
if [[ "$joined" == *"pg_dump"* ]]; then printf '%s\\n' '-- PostgreSQL database dump' 'SELECT 1;'; exit "${QBOT_TEST_DUMP_STATUS:-0}"; fi
if [[ "$joined" == *"SELECT CASE WHEN"* ]]; then printf '%s\\n' "${QBOT_TEST_SCHEMA:-1}"; exit 0; fi
if [[ "$joined" == *"SELECT version_num"* ]]; then printf '%s\\n' "${QBOT_TEST_REVISION:-0015_ws_tickets}"; exit 0; fi
if [[ "$joined" == *"psql"* ]]; then
  cat > /dev/null
  if [[ "$joined" == *'"$POSTGRES_DB"'* ]]; then exit "${QBOT_TEST_RESTORE_STATUS:-0}"; fi
fi
exit 0
''')

    def write_command(self, name, source):
        target = self.bin / name
        target.write_text(source, encoding="utf-8", newline="\n")
        target.chmod(0o755)

    def run_script(self, script="restore.sh", *, verify_only=False, **overrides):
        arguments = [str(BASH), "-c", 'export PATH="$QBOT_TEST_BIN:$PATH"; exec bash "$@"', "qbot-test", script]
        if script == "restore.sh":
            if verify_only:
                arguments.append("--verify-only")
            arguments.append("input.sql.gz")
        binary = self.bin.as_posix()
        if os.name == "nt":
            binary = "/" + binary[0].lower() + binary[2:]
        result = subprocess.run(arguments, cwd=self.root, input=b"RESTORE\n", capture_output=True, env={
                                    **os.environ, "QBOT_ENV_FILE": ".env", "QBOT_TEST_LOG": str(self.log),
                                    "QBOT_TEST_BIN": binary, **overrides,
                                })
        result.stdout = result.stdout.decode("utf-8", errors="replace")
        result.stderr = result.stderr.decode("utf-8", errors="replace")
        commands = self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []
        return result, commands

    def test_verify_only_rejects_archive_without_required_schema_before_service_stop(self):
        result, commands = self.run_script(verify_only=True, QBOT_TEST_SCHEMA="0")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertTrue(any("createdb" in command for command in commands))
        self.assertTrue(any("dropdb" in command for command in commands))
        self.assertFalse(any("\tstop\t" in command for command in commands))

    def test_unknown_revision_refused_before_service_stop(self):
        result, commands = self.run_script(verify_only=True, QBOT_TEST_REVISION="future_unknown_schema")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse(any("\tstop\t" in command for command in commands))

    def test_verify_only_uses_transaction_and_never_changes_running_database(self):
        result, commands = self.run_script(verify_only=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        restores = [command for command in commands if "psql" in command and "-c " not in command]
        self.assertEqual(len(restores), 1)
        self.assertIn("--single-transaction", restores[0])
        self.assertFalse(any("\tstop\t" in command or "pg_dump" in command for command in commands))

    def test_restore_failure_keeps_services_stopped_and_pre_restore_snapshot(self):
        result, commands = self.run_script(QBOT_TEST_RESTORE_STATUS="19")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertTrue(any("\tstop\tbackend\tworker" in command for command in commands))
        self.assertFalse(any("\tstart\t" in command for command in commands))
        restores = [command for command in commands if "psql" in command and "-c " not in command]
        self.assertEqual(len(restores), 2)
        self.assertTrue(all("--single-transaction" in command for command in restores))
        dump_index = next(index for index, command in enumerate(commands) if "pg_dump" in command)
        production_index = next(index for index, command in enumerate(commands) if '"$POSTGRES_DB"' in command and "psql" in command)
        self.assertLess(dump_index, production_index)
        snapshots = list((self.root / "backups").glob("qbot-*.sql.gz"))
        self.assertEqual(len(snapshots), 1)
        self.assertTrue(snapshots[0].with_name(snapshots[0].name + ".sha256").is_file())

    def test_failed_pre_restore_snapshot_prevents_production_write_and_retention(self):
        backups = self.root / "backups"
        backups.mkdir()
        for index in range(16):
            (backups / f"qbot-old-{index}.sql.gz").write_bytes(gzip.compress(b"old valid dump"))
        result, commands = self.run_script(QBOT_TEST_DUMP_STATUS="17")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertTrue(any("\tstop\t" in command for command in commands))
        self.assertFalse(any("\tstart\t" in command for command in commands))
        self.assertFalse(any('"$POSTGRES_DB"' in command and "psql" in command for command in commands))
        self.assertEqual(len(list(backups.glob("qbot-*.sql.gz"))), 16)
        self.assertEqual(list(backups.glob(".qbot-backup-*")), [])

    def test_failed_compression_in_actual_backup_script_does_not_prune(self):
        backups = self.root / "backups"
        backups.mkdir()
        for index in range(16):
            (backups / f"qbot-old-{index}.sql.gz").write_bytes(gzip.compress(b"old valid dump"))
        self.write_command("gzip", "#!/usr/bin/env bash\nprintf partial-compressed-data\nexit 18\n")
        result, _ = self.run_script("backup.sh")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(len(list(backups.glob("qbot-*.sql.gz"))), 16)
        self.assertEqual(list(backups.glob(".qbot-backup-*")), [])


if __name__ == "__main__":
    unittest.main()
