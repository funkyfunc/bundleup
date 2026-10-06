"""Target presets (ADR-0014, ADR-0025): named shorthands for ordinary flags (`--format`,
`--python`, `--python-platform`) that always say what they expand to. Explicit flags win.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from ._errors import UsageError

if TYPE_CHECKING:
    from ._build import BuildOptions

# Lambda runs Python 3.10 and 3.11 on Amazon Linux 2 (glibc 2.26: manylinux_2_17 is the newest
# level uv offers that fits) and 3.12+ on Amazon Linux 2023 (glibc 2.34). Checked 2026-10-05:
# https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html (3.15 is in preview).
LAMBDA_PYTHONS = ("3.10", "3.11", "3.12", "3.13", "3.14", "3.15")
VERSION = re.compile(r"(?P<major>\d+)\.(?P<minor>\d+)")


def _lambda_platform(arch: str) -> Callable[[str], str]:
    def platform(python: str) -> str:
        match = VERSION.fullmatch(python)
        if match and python not in LAMBDA_PYTHONS:
            raise UsageError(
                f"AWS Lambda has no Python {python} runtime",
                hint=f"use one of {', '.join(LAMBDA_PYTHONS)} (--python)",
            )
        old = match is not None and (int(match["major"]), int(match["minor"])) < (3, 12)
        return f"{arch}-manylinux_2_17" if old else f"{arch}-manylinux_2_34"

    return platform


@dataclass(frozen=True)
class Preset:
    """A named target: what it builds, for which Python and platform."""

    name: str
    description: str
    format: str
    python: str  # the default; --python overrides it
    platform_for: Callable[[str], str]  # the Python version -> uv platform name

    def expansion(self, python: str | None = None) -> list[str]:
        """The flags this preset stands for (with `python` instead of the default, if given)."""
        python = python or self.python
        return [
            "--format",
            self.format,
            "--python",
            python,
            "--python-platform",
            self.platform_for(python),
        ]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "format": self.format,
            "python": self.python,
            "python_platform": self.platform_for(self.python),
            "expansion": self.expansion(),
        }


PRESETS = {
    p.name: p
    for p in (
        Preset(
            "lambda",
            "AWS Lambda function zip, x86_64 (handler: module.function)",
            "lambda",
            "3.13",
            _lambda_platform("x86_64"),
        ),
        Preset(
            "lambda-arm64",
            "AWS Lambda function zip, arm64 (Graviton)",
            "lambda",
            "3.13",
            _lambda_platform("aarch64"),
        ),
        Preset(
            # Claude API code execution and Skills: Python 3.11, Linux x86_64, no network
            # (platform.claude.com docs, checked 2026-10-05). Its glibc isn't documented, so the
            # most compatible manylinux level (ADR-0013).
            "claude-api",
            "Claude API code execution and Skills sandbox: Python 3.11, Linux x86_64, no network",
            "pyz",
            "3.11",
            lambda _python: "x86_64-manylinux_2_17",
        ),
    )
}


def list_targets() -> list[Preset]:
    """Every preset, by name."""
    return [PRESETS[name] for name in sorted(PRESETS)]


def find(name: str) -> Preset:
    preset = PRESETS.get(name)
    if preset is None:
        import difflib  # only on this error path

        close = difflib.get_close_matches(name, PRESETS, n=1)
        hint = f"did you mean `--target {close[0]}`?" if close else None
        raise UsageError(
            f"unknown target `{name}`",
            hint=hint or f"targets: {', '.join(sorted(PRESETS))} (`bundleup targets` lists them)",
        )
    return preset


def apply(options: BuildOptions) -> tuple[BuildOptions, list[str]]:
    """Fill in what `options.target` stands for, keeping every explicitly set value. Returns the
    expanded options (with `target` cleared) and the flags as they were applied, to print."""
    if options.target is None:
        return options, []
    preset = find(options.target)
    python = options.python or preset.python
    if options.python and not VERSION.fullmatch(options.python) and not options.python_platform:
        raise UsageError(
            f"--target {preset.name} needs a Python version, not a path, to choose the platform",
            hint="pass --python 3.12 (a version), or --python-platform as well",
        )
    expanded = replace(
        options,
        target=None,
        format=options.format or preset.format,
        python=python,
        python_platform=options.python_platform or preset.platform_for(python),
    )
    flags = [
        "--format",
        expanded.format or "pyz",
        "--python",
        python,
        "--python-platform",
        expanded.python_platform or "",
    ]
    return expanded, flags
