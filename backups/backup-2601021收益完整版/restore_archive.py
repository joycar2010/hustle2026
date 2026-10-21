"""Authenticate and decrypt backup to a NEW tar.gz, without deploying it.

python restore_archive.py --key /secure/restore.key --output /restore/polyauto.tar.gz
Requires Python 3 and OpenSSL. Never put restore.key in this repository.
"""
import argparse
import hashlib
import hmac
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    archive = root / 'polyauto-complete.tar.gz.enc'
    mac_key = hmac.new(args.key.read_bytes().strip(), b'polyauto-backup-auth-v1', hashlib.sha256).digest()
    mac = hmac.new(mac_key, digestmod=hashlib.sha256)
    with archive.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            mac.update(chunk)
    expected = (root / 'polyauto-complete.tar.gz.enc.hmac').read_text().strip()
    if not hmac.compare_digest(mac.hexdigest(), expected):
        raise SystemExit('Authentication failed: wrong key or changed ciphertext.')
    # Create owner-only plaintext and never overwrite an existing restore file.
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_BINARY', 0)
    with os.fdopen(os.open(args.output, flags, 0o600), 'wb') as out:
        subprocess.run(['openssl', 'enc', '-d', '-aes-256-cbc', '-pbkdf2', '-iter', '200000',
                        '-pass', 'file:' + str(args.key), '-in', str(archive)], stdout=out, check=True)
    print('Authenticated archive decrypted to', args.output)
    print('Review and extract into an empty staging directory; do not overwrite a running deployment.')


if __name__ == '__main__':
    main()
