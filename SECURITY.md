# Security Policy

## Supported Versions

Until `1.0`, only the latest `0.x.y` release on PyPI receives security fixes.

| Version | Supported |
|---|---|
| `0.2.x` | Yes |
| `< 0.2.0` | No |

## Reporting a Vulnerability

If you discover a security vulnerability in `bundleup` (for example, path traversal during bundle extraction, cache poisoning, or lockfile/hash verification bypass), please report it privately via [GitHub Security Advisories](https://github.com/funkyfunc/bundleup/security/advisories/new) rather than opening a public issue.

Please include:

- A description of the vulnerability and its impact.
- Minimal steps or a proof-of-concept archive/project to reproduce it.
- Affected versions and platforms (Linux, macOS, Windows).

## Security Model Notes

- **`bundleup verify` checks integrity, not authenticity:** `bundleup verify` verifies that a bundle and its unpacked cache match the SHA-256 digests recorded in `bundleup-manifest.json` and `uv.lock` / `pylock.toml`. It detects accidental corruption or local cache tampering, not a maliciously authored bundle.
- **Unpack cache trust (`_loader.py`):** Unpacked bundles are stored under the user's cache directory (`BUNDLEUP_CACHE`, `~/Library/Caches/bundleup`, `~/.cache/bundleup`, or `%LOCALAPPDATA%\bundleup\Cache`) and verified against ownership and permission invariants before execution.
