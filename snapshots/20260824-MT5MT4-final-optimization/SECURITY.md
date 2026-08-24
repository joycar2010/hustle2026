# Backup handling

The upstream GitHub repository is public. Exact credentials, bridge tokens,
TLS private keys, PostgreSQL data, Redis data, and account environment files
are therefore stored only in the encrypted, split artifact under `database/`.
Keep the corresponding local key file offline and rotate any credential if
the key is lost or exposed. The redacted deployment templates retain paths,
ports, service names, and all non-secret operational settings.
