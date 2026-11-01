"""Authenticate a backup, then decrypt into a NEW file without deploying it."""
import argparse
import hashlib
import hmac
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--openssl', default='openssl')
    args = parser.parse_args()
    if not args.verify_only and args.output is None:
        parser.error('--output is required unless --verify-only')
    root = Path(__file__).resolve().parent
    encrypted = root / 'poly-complete.tar.gz.enc'
    derived = hmac.new(args.key.read_bytes().strip(), b'polyauto-backup-auth-v1', hashlib.sha256).digest()
    mac = hmac.new(derived, digestmod=hashlib.sha256)
    with encrypted.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            mac.update(chunk)
    expected = (root / 'poly-complete.tar.gz.enc.hmac').read_text().strip()
    if not hmac.compare_digest(mac.hexdigest(), expected):
        raise SystemExit('Authentication failed: wrong key or changed ciphertext')
    if args.verify_only:
        print('Encrypted archive authentication passed')
        return
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_BINARY', 0)
    with os.fdopen(os.open(args.output, flags, 0o600), 'wb') as out:
        subprocess.run([args.openssl, 'enc', '-d', '-aes-256-cbc', '-pbkdf2', '-iter', '200000',
                        '-pass', 'file:' + str(args.key), '-in', str(encrypted)], stdout=out, check=True)
    print('Authenticated archive decrypted to', args.output)
    print('Extract only into an empty staging directory; do not overwrite a running deployment.')


if __name__ == '__main__':
    main()
