#!/usr/bin/env python3
"""Back up the CMT database and encrypt the copy.

Set AGE_RECIPIENT (preferred) or GPG_RECIPIENT. The plaintext copy is removed
after encryption. Install age (https://age-encryption.org) or GnuPG; both are free.
"""

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def database_path():
    configured = os.environ.get('DATABASE_URL', '')
    if configured.startswith('sqlite:///'):
        return configured[len('sqlite:///'):]
    if configured.startswith('postgres'):
        return None
    return os.path.join('instance', 'cmt.db')


def snapshot_sqlite(source, destination):
    """Copy a live SQLite file without reading a half-written page."""
    original = sqlite3.connect(source)
    copy = sqlite3.connect(destination)
    try:
        original.backup(copy)
    finally:
        copy.close()
        original.close()


def encrypt_file(source, destination, env=None):
    """Encrypt source to destination. Returns an error string, or None."""
    env = os.environ if env is None else env
    age_recipient = (env.get('AGE_RECIPIENT') or '').strip()
    gpg_recipient = (env.get('GPG_RECIPIENT') or '').strip()
    if age_recipient:
        program = shutil.which('age')
        if not program:
            return 'age is not installed. Install age, or set GPG_RECIPIENT instead.'
        command = [program, '-r', age_recipient, '-o', str(destination), str(source)]
    elif gpg_recipient:
        program = shutil.which('gpg')
        if not program:
            return 'gpg is not installed. Install GnuPG, or set AGE_RECIPIENT instead.'
        command = [
            program, '--batch', '--yes', '--encrypt',
            '--recipient', gpg_recipient,
            '--output', str(destination),
            str(source),
        ]
    else:
        return 'Set AGE_RECIPIENT or GPG_RECIPIENT. Backups are not written in plaintext.'
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or 'encryption failed').strip()
        return message
    return None


def backup(output_dir='backups'):
    """Create one encrypted backup. Returns (exit code, message)."""
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    database_url = os.environ.get('DATABASE_URL', '')
    if database_url.startswith('postgres'):
        dump_program = shutil.which('pg_dump')
        if not dump_program:
            return 1, 'pg_dump is not installed, so the Postgres database was not backed up.'
        plaintext = out_dir / f'cmt-{stamp}.sql'
        result = subprocess.run(
            [dump_program, '--dbname', database_url, '--file', str(plaintext), '--no-owner'],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            plaintext.unlink(missing_ok=True)
            return 1, (result.stderr or 'pg_dump failed').strip()
    else:
        source = database_path()
        if not source or not os.path.exists(source):
            return 1, f'Database file was not found at {source}.'
        handle, raw_path = tempfile.mkstemp(prefix='cmt-backup-', suffix='.sqlite')
        os.close(handle)
        plaintext = Path(raw_path)
        snapshot_sqlite(source, plaintext)

    encrypted = out_dir / (f'cmt-{stamp}.sql.age' if database_url.startswith('postgres') else f'cmt-{stamp}.sqlite.age')
    if (os.environ.get('GPG_RECIPIENT') or '').strip() and not (os.environ.get('AGE_RECIPIENT') or '').strip():
        encrypted = encrypted.with_suffix('.gpg')
    error = encrypt_file(plaintext, encrypted)
    plaintext.unlink(missing_ok=True)
    if error:
        encrypted.unlink(missing_ok=True)
        return 1, error
    return 0, f'Encrypted backup written to {encrypted}'


def main():
    code, message = backup(os.environ.get('BACKUP_DIR', 'backups'))
    print(message)
    return code


if __name__ == '__main__':
    sys.exit(main())
