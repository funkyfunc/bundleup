"""Private registry, proxy, TLS, and pip.conf diagnostics.

uv intentionally ignores pip's configuration (`pip.conf`, `PIP_INDEX_URL`, `PIP_CERT`), and
restricted networks fail in three distinct ways:
1. uv hits public PyPI and is blocked while `pip.conf` already points at a custom index;
2. a private registry lists a package version in `/simple/`, then returns HTTP 403 on its wheel
   (access policy or missing upstream cache permission);
3. external binary downloads from GitHub (`--format exe`'s launcher or `uv python install`) return
   HTTP 403 or fail TLS verification under an HTTPS-inspecting proxy.

Nothing here runs on the happy path: `pip`'s configuration is inspected only when a network or
registry failure occurs, with embedded credentials redacted from every URL.
"""

from __future__ import annotations

import configparser
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import InvalidWheelFilename, canonicalize_name, parse_wheel_filename

from . import _toml as tomllib
from ._errors import UvError

_SECRET_QUERY_KEYS = frozenset(
    {"token", "access_token", "auth", "apikey", "api_key", "password", "secret", "sig", "signature"}
)
_CRED_URL = re.compile(r"https?://[^\s'\"<>()]+")
_HTTP_STATUS = re.compile(
    r"(?:HTTP status (?:client|server) error \((\d{3})\b[^)]*\)\s+for url \(([^)]+)\)"
    r"|HTTP Error (\d{3})\b"
    r"|status code (\d{3})\b)",
    re.IGNORECASE,
)
_TLS_PATTERNS = (
    "unknownissuer",
    "certificate verify failed",
    "invalid peer certificate",
    "self-signed certificate",
    "self signed certificate",
    "unable to get local issuer certificate",
)
_PUBLIC_HOSTS = frozenset({"pypi.org", "files.pythonhosted.org", "github.com"})


@dataclass(frozen=True)
class PipConfig:
    """Managed pip settings (`pip.conf` / `pip.ini` / `PIP_*`) with credentials redacted."""

    index_url: str | None = None
    extra_index_urls: tuple[str, ...] = ()
    cert: str | None = None
    source: str | None = None


def redact_url(raw: str) -> str:
    """Strip userinfo (`user:token@`) and secret query parameters from an HTTP(S) URL."""
    stripped = raw.strip()
    try:
        parts = urlsplit(stripped)
    except ValueError:
        return re.sub(r"(https?://)[^/@\s]+@", r"\1", stripped)
    if not parts.scheme or not parts.netloc:
        return stripped
    host = parts.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        port = None
    netloc = f"{host}:{port}" if port else host
    query = parts.query
    if query:
        pairs = [
            (k, "<redacted>" if k.lower() in _SECRET_QUERY_KEYS else v)
            for k, v in parse_qsl(query, keep_blank_values=True)
        ]
        query = urlencode(pairs)
    return urlunsplit((parts.scheme, netloc, parts.path, query, ""))


def _redact_match(match: re.Match[str]) -> str:
    url = match.group(0)
    trail = ""
    while url and url[-1] in ".,;":
        trail = url[-1] + trail
        url = url[:-1]
    return redact_url(url) + trail


def redact_text(text: str) -> str:
    """Redact credentials from any HTTP(S) URLs appearing inside `text`."""
    return _CRED_URL.sub(_redact_match, text)


def _pip_config_paths(env: Mapping[str, str], home: Path) -> list[Path]:
    paths: list[Path] = []
    explicit = env.get("PIP_CONFIG_FILE", "").strip()
    if explicit and explicit != os.devnull:
        paths.append(Path(explicit))
    xdg = env.get("XDG_CONFIG_HOME", "").strip()
    paths.append((Path(xdg) if xdg else home / ".config") / "pip" / "pip.conf")
    paths.append(home / ".pip" / "pip.conf")
    if sys.platform == "darwin":
        paths.append(home / "Library" / "Application Support" / "pip" / "pip.conf")
        paths.append(Path("/Library/Application Support/pip/pip.conf"))
    if os.name == "nt":
        appdata = env.get("APPDATA", "").strip()
        if appdata:
            paths.append(Path(appdata) / "pip" / "pip.ini")
        paths.append(home / "pip" / "pip.ini")
        progdata = env.get("PROGRAMDATA", "").strip()
        if progdata:
            paths.append(Path(progdata) / "pip" / "pip.ini")
    else:
        paths.append(Path("/etc/pip.conf"))
        paths.append(Path("/etc/xdg/pip/pip.conf"))
    return paths


def read_pip_config(env: Mapping[str, str] | None = None, *, home: Path | None = None) -> PipConfig:
    """Inspect `PIP_*` environment variables and standard `pip.conf` / `pip.ini` files."""
    eff_env = os.environ if env is None else env
    eff_home = home if home is not None else Path.home()
    index_url: str | None = None
    extras: list[str] = []
    cert: str | None = None
    source: str | None = None

    env_idx = eff_env.get("PIP_INDEX_URL", "").strip()
    if env_idx:
        index_url = redact_url(env_idx)
        source = "PIP_INDEX_URL"
    env_extra = eff_env.get("PIP_EXTRA_INDEX_URL", "").strip()
    if env_extra:
        extras.extend(redact_url(u) for u in env_extra.split() if u.strip())
        source = source or "PIP_EXTRA_INDEX_URL"
    env_cert = eff_env.get("PIP_CERT", "").strip()
    if env_cert:
        cert = env_cert
        source = source or "PIP_CERT"

    for cfg_path in _pip_config_paths(eff_env, eff_home):
        try:
            if not cfg_path.is_file():
                continue
            parser = configparser.RawConfigParser()
            parser.read(cfg_path, encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError, configparser.Error):
            continue
        for section in ("global", "install"):
            if not parser.has_section(section):
                continue
            if index_url is None and parser.has_option(section, "index-url"):
                raw = parser.get(section, "index-url").strip()
                if raw:
                    index_url = redact_url(raw)
                    source = source or str(cfg_path)
            if parser.has_option(section, "extra-index-url"):
                raw_extra = parser.get(section, "extra-index-url")
                for item in raw_extra.split():
                    if item.strip():
                        red = redact_url(item)
                        if red not in extras:
                            extras.append(red)
                            source = source or str(cfg_path)
            if cert is None and parser.has_option(section, "cert"):
                raw_cert = parser.get(section, "cert").strip()
                if raw_cert:
                    cert = raw_cert
                    source = source or str(cfg_path)
    return PipConfig(
        index_url=index_url,
        extra_index_urls=tuple(extras),
        cert=cert,
        source=source,
    )


def uv_has_custom_index(
    workdir: Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> bool:
    """Whether uv already has a custom package index configured via env, uv.toml, or project."""
    eff_env = os.environ if env is None else env
    eff_home = home if home is not None else Path.home()
    if any(
        eff_env.get(k, "").strip()
        for k in ("UV_DEFAULT_INDEX", "UV_INDEX", "UV_INDEX_URL", "UV_EXTRA_INDEX_URL")
    ):
        return True
    uv_tomls: list[Path] = []
    explicit = eff_env.get("UV_CONFIG_FILE", "").strip()
    if explicit:
        uv_tomls.append(Path(explicit))
    xdg = eff_env.get("XDG_CONFIG_HOME", "").strip()
    uv_tomls.append((Path(xdg) if xdg else eff_home / ".config") / "uv" / "uv.toml")
    if os.name == "nt":
        appdata = eff_env.get("APPDATA", "").strip()
        if appdata:
            uv_tomls.append(Path(appdata) / "uv" / "uv.toml")
    else:
        uv_tomls.append(Path("/etc/uv/uv.toml"))
    if workdir is not None:
        uv_tomls.append(workdir / "uv.toml")
        pyproject = workdir / "pyproject.toml"
        try:
            if pyproject.is_file():
                text = pyproject.read_text(encoding="utf-8-sig", errors="ignore")
                if "[[tool.uv.index]]" in text or "index-url" in text:
                    return True
        except OSError:
            pass
    for path in uv_tomls:
        try:
            if path.is_file():
                text = path.read_text(encoding="utf-8-sig", errors="ignore")
                if "[[index]]" in text or "index-url" in text:
                    return True
        except OSError:
            pass
    return False


def _pip_mismatch_hint(
    workdir: Path | None,
    *,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> str | None:
    eff_env = os.environ if env is None else env
    if uv_has_custom_index(workdir, env=eff_env, home=home):
        return None
    pip_cfg = read_pip_config(eff_env, home=home)
    chosen = pip_cfg.index_url or (
        pip_cfg.extra_index_urls[0] if pip_cfg.extra_index_urls else None
    )
    if not chosen:
        return None
    host = urlsplit(chosen).hostname or ""
    if host.lower() in ("pypi.org", "files.pythonhosted.org"):
        return None
    where = f" ({pip_cfg.source})" if pip_cfg.source else ""
    return (
        f"pip is configured to use {chosen}{where}, which uv ignores; set "
        f"UV_DEFAULT_INDEX={chosen} or add it as `[[index]]` in ~/.config/uv/uv.toml"
    )


def _tls_hint(
    *,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> str:
    eff_env = os.environ if env is None else env
    pip_cfg = read_pip_config(eff_env, home=home)
    cert_note = (
        f" (pip uses {pip_cfg.cert}: set SSL_CERT_FILE={pip_cfg.cert})"
        if pip_cfg.cert and not eff_env.get("SSL_CERT_FILE")
        else ""
    )
    return (
        "if an HTTPS proxy uses a custom CA, set UV_NATIVE_TLS=1 to trust the system "
        f"certificate store, or set SSL_CERT_FILE=<ca-bundle.pem>{cert_note}"
    )


def _extract_status_and_url(detail: str) -> tuple[int | None, str | None]:
    match = _HTTP_STATUS.search(detail)
    status = int(next(g for g in match.groups() if g and g.isdigit())) if match else None
    url = match.group(2) if match and match.group(2) else None
    if url is None:
        urls = _CRED_URL.findall(detail)
        url = urls[0].rstrip(".,);'\"") if urls else None
    return status, redact_url(url) if url else None


def _describe_artifact(url: str) -> tuple[str | None, str | None, str]:
    """Return `(package_name, wheel_summary, host)` from a wheel or sdist URL."""
    parsed = urlsplit(url)
    host = parsed.hostname or url
    filename = parsed.path.rsplit("/", 1)[-1]
    if filename.endswith(".whl"):
        try:
            name, ver, _build, tags = parse_wheel_filename(filename)
            sample = next(iter(sorted(tags, key=str)), None)
            tag_str = f"{sample.interpreter}-{sample.abi}-{sample.platform}" if sample else "wheel"
            return canonicalize_name(name), f"{canonicalize_name(name)} {ver} ({tag_str})", host
        except InvalidWheelFilename:
            return None, filename, host
    sdist = re.match(
        r"^([A-Za-z0-9][A-Za-z0-9._-]*?)-(\d[A-Za-z0-9._+-]*)\.(?:tar\.gz|zip)$", filename
    )
    if sdist:
        pkg = canonicalize_name(sdist.group(1))
        return pkg, f"{pkg} {sdist.group(2)} (source archive)", host
    return None, None, host


def is_tls_error(text: str) -> bool:
    low = text.lower()
    return any(p in low for p in _TLS_PATTERNS)


def _missing_no_proxy_hint(host: str, env: Mapping[str, str] | None = None) -> str | None:
    """When `HTTPS_PROXY` / `HTTP_PROXY` is set and an internal `host` isn't in `NO_PROXY`."""
    eff_env = os.environ if env is None else env
    clean_host = host.strip().lower().strip("[]")
    if not clean_host or clean_host in _PUBLIC_HOSTS:
        return None
    proxy_vars = (
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "ALL_PROXY",
        "all_proxy",
    )
    if not any(eff_env.get(k, "").strip() for k in proxy_vars):
        return None
    raw_no_proxy = eff_env.get("NO_PROXY") or eff_env.get("no_proxy") or ""
    for item in raw_no_proxy.split(","):
        pat = item.strip().lower()
        if not pat:
            continue
        if pat == "*":
            return None
        pat_host = pat.rsplit(":", 1)[0] if ":" in pat and not pat.startswith("[") else pat
        suffix = pat_host.lstrip(".")
        if clean_host == suffix or clean_host.endswith(f".{suffix}"):
            return None
    return (
        f"HTTPS_PROXY is set while {clean_host} isn't in NO_PROXY—if {clean_host} is an internal "
        f"host, add it to NO_PROXY so requests bypass the external proxy"
    )


def _project_build_backends(workdir: Path | None) -> list[str]:
    if workdir is None:
        return []
    pyproject = workdir / "pyproject.toml"
    try:
        if not pyproject.is_file():
            return []
        data = tomllib.loads(pyproject.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError):
        return []
    build_sys = data.get("build-system")
    reqs = build_sys.get("requires") if isinstance(build_sys, dict) else None
    if not isinstance(reqs, list):
        return []
    names: list[str] = []
    for raw in reqs:
        if not isinstance(raw, str):
            continue
        try:
            pkg = canonicalize_name(Requirement(raw).name)
        except InvalidRequirement:
            pkg = re.split(r"[<>=!~;\[\s]", raw, maxsplit=1)[0].strip()
        if pkg and pkg not in names:
            names.append(pkg)
    return names


def _build_backend_diagnostic(detail: str, workdir: Path | None) -> tuple[str, str] | None:
    """Detect isolated PEP 517 `[build-system]` failures in offline / wheelhouse builds."""
    low = detail.lower()
    is_build_dep_err = (
        "resolving build dependencies" in low
        or "build-system.requires" in low
        or (
            "failed to build" in low
            and (
                "was not found in the cache" in low
                or "was not found in the package registry" in low
                or "offline" in low
            )
        )
    )
    if not is_build_dep_err:
        return None
    backends = _project_build_backends(workdir)
    shown = (
        ", ".join(backends) if backends else "build-system packages (e.g. hatchling, setuptools)"
    )
    dl_args = " ".join(backends) if backends else "hatchling setuptools wheel"
    return (
        f"missing [build-system] package(s) ({shown}) while building the project wheel",
        "`pip download` and `uv export` only fetch runtime dependencies, not `[build-system]` "
        f"packages; add them to your wheelhouse (`pip download --only-binary=:all: -d <wheelhouse> "
        f"{dl_args}`), or set `[tool.uv] package = false` in pyproject.toml for a dependency-only "
        "bundle",
    )


def diagnose_uv_error(
    error: UvError,
    *,
    workdir: Path | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> UvError:
    """Enrich a `UvError` with registry, proxy, wheelhouse, TLS, or `pip.conf` guidance."""
    raw_detail = error.detail or ""
    if not raw_detail or error.hint:
        return error
    detail = redact_text(raw_detail)
    status, url = _extract_status_and_url(detail)
    pip_hint = _pip_mismatch_hint(workdir, env=env, home=home)
    host = (urlsplit(url).hostname or url) if url else ""
    no_proxy_hint = _missing_no_proxy_hint(host, env=env) if host else None

    if status == 407:
        where = f" while reaching {host}" if host else ""
        proxy_hint = (
            "check HTTPS_PROXY / HTTP_PROXY credentials (or use a local proxy forwarder if your "
            "proxy requires NTLM/Kerberos authentication)"
        )
        if no_proxy_hint:
            proxy_hint = f"{proxy_hint}; {no_proxy_hint}"
        return UvError(
            f"proxy authentication required (HTTP 407){where}",
            hint=proxy_hint,
            detail=detail,
        )

    if status in (502, 503, 504) and host and no_proxy_hint:
        return UvError(
            f"proxy error (HTTP {status}) reaching {host}",
            hint=no_proxy_hint,
            detail=detail,
        )

    if status in (401, 403) and url:
        pkg, artifact, art_host = _describe_artifact(url)
        if status == 403 and artifact and pkg:
            hint = (
                f"the index advertised this version, but denied downloading its file "
                f"(access policy or upstream cache permission); constrain `{pkg}` to an "
                "allowed version and re-lock—do not fall back to a public index unless intended"
            )
            if art_host.lower() in _PUBLIC_HOSTS and pip_hint:
                hint = f"{pip_hint}; otherwise {hint}"
            elif no_proxy_hint:
                hint = f"{hint}; {no_proxy_hint}"
            return UvError(
                f"registry denied access (HTTP 403) to {artifact} on {art_host}",
                hint=hint,
                detail=detail,
            )
        auth_hint = (
            "check index credentials (~/.netrc, keyring, or UV_INDEX_<NAME>_USERNAME / _PASSWORD)"
        )
        if art_host.lower() in _PUBLIC_HOSTS and pip_hint:
            auth_hint = pip_hint
        elif pip_hint:
            auth_hint = f"{auth_hint}; {pip_hint}"
        if no_proxy_hint:
            auth_hint = f"{auth_hint}; {no_proxy_hint}"
        return UvError(
            f"registry denied access (HTTP {status}) to {art_host}",
            hint=auth_hint,
            detail=detail,
        )

    if is_tls_error(detail):
        tls = _tls_hint(env=env, home=home)
        hint = f"{tls}; {pip_hint}" if pip_hint else tls
        return UvError(
            f"{error.message}: TLS certificate verification failed",
            hint=hint,
            detail=detail,
        )

    backend_diag = _build_backend_diagnostic(detail, workdir)
    if backend_diag is not None:
        b_msg, b_hint = backend_diag
        if pip_hint:
            b_hint = f"{b_hint}; {pip_hint}"
        return UvError(f"{error.message}: {b_msg}", hint=b_hint, detail=detail)

    if pip_hint and any(
        w in detail.lower()
        for w in (
            "failed to fetch",
            "failed to download",
            "client error",
            "connection refused",
            "timed out",
            "dns error",
            "network is unreachable",
            "not found",
        )
    ):
        return UvError(error.message, hint=pip_hint, detail=detail)

    if detail != raw_detail:
        return UvError(error.message, hint=error.hint, detail=detail)
    return error


def diagnose_runtime_download(
    url_or_key: str,
    error_text: str,
    *,
    kind: Literal["launcher", "interpreter", "exe-python"],
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> tuple[str, str]:
    """Plain-language `(message, hint)` when a standalone Python or launcher download is blocked."""
    clean_err = redact_text(error_text)
    target = redact_url(url_or_key)
    status, _ = _extract_status_and_url(clean_err)
    blocked = f" (HTTP {status}: blocked by network or proxy)" if status in (401, 403) else ""
    tls_extra = f"; {_tls_hint(env=env, home=home)}" if is_tls_error(clean_err) else ""
    if kind == "launcher":
        return (
            f"couldn't download the standalone launcher from {target}{blocked} ({clean_err})",
            "where Python is installed, build a `.pyz` (the default) instead—it needs no launcher "
            "or runtime download; for `--format exe` behind a firewall, set BUNDLEUP_JUMP_MIRROR "
            f"to an internal mirror or folder{tls_extra}",
        )
    if kind == "exe-python":
        return (
            f"couldn't download standalone Python {target} for `--format exe`{blocked}",
            "where Python is installed, build a `.pyz` (the default) instead—it needs no runtime "
            "download; for `--format exe` behind a firewall, set UV_PYTHON_INSTALL_MIRROR to an "
            f"internal mirror{tls_extra}",
        )
    return (
        f"couldn't download Python {target}{blocked}",
        "bundles for `.pyz` assemble wheels without extra interpreters by default; behind a "
        "firewall, leave interpreter downloads off or set UV_PYTHON_INSTALL_MIRROR to an internal "
        f"mirror{tls_extra}",
    )
