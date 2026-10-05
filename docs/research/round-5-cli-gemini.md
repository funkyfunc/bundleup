# **Architecture and CLI Specification for High-Performance Developer Tools: A Style Guide for bundleup**

Modern software engineering tooling has undergone a structural shift toward extreme execution speed, ergonomic predictability, and unified operational interfaces. Developers now expect command-line utilities to start instantaneously, emit readable diagnostics, and integrate reliably into automated continuous integration (CI) pipelines and autonomous agentic workflows. This standard has been established by systems tools such as esbuild, uv, Ruff, and cargo1.  
A Python packaging and self-contained executable bundler such as bundleup must adhere to these established terminal and API paradigms. The tool must operate consistently across four distinct execution environments: interactive developer terminals, non-interactive CI/CD runners, autonomous AI agents issuing shell commands and parsing structured data, and programmatic Python runtimes calling internal packaging engines.  
This document establishes the architectural foundation, design principles, and concrete implementation guidelines for bundleup. It begins with a comparative analysis of modern developer tools, examines CLI and library interface architecture, presents a numbered style guide covering CLI and API design, details concrete terminal and schema mockups, specifies configuration and exit hierarchies, and provides an implementation blueprint optimized for sub-millisecond Python runtimes.

## **Comparative Tool Analysis: Foundations from Modern Developer Tooling**

High-performance developer tools balance human ergonomics with machine parsability. The following comparative analysis examines the architectural decisions, strengths, and failure modes across eleven foundational CLI tools and the Command Line Interface Guidelines (clig.dev)5.

### **Astral Ecosystem: uv and Ruff**

Astral tools (uv, Ruff) prioritize execution speed and clean diagnostic output1. Both tools achieve cold-start runtimes under 10 milliseconds by utilizing compiled Rust binaries and minimizing filesystem scanning overhead1.  
The diagnostic reporting in uv models modern compiler diagnostics rather than dumping raw Python tracebacks6. When a build fails, uv formats the failure into a structural tree that isolates the root cause, downstream effect, and operational hints6. Furthermore, uv unifies previously fragmented packaging lifecycles (uv run, uv lock, uv add, uv tool) around declarative pyproject.toml manifests2.  
A major architectural trade-off in both uv and Ruff is the deliberate absence of an exposed, public Python library API. Python applications cannot invoke uv in-process; they must spawn subprocesses, incurring serialization overhead and child-process management complexity8.  
× Failed to build numpy==1.19.5 ├─▶ The build backend returned an error ╰─▶ Call to setuptools.build\_meta:build\_wheel failed with exit status: 1 \[stderr\] Traceback (most recent call last): File "setup.py", line 42, in raise RuntimeError("Python 3.13 is unsupported") RuntimeError: Python 3.13 is unsupported  
hint: This usually indicates a problem with the package or the build environment.

### **Rust Toolchain: cargo**

The Rust package manager and compiler driver, cargo, serves as the industry benchmark for deterministic package management, compilation workflows, and predictable progress tracking4. Its human-facing interface uses color-coded status prefixes right-aligned to a 12-character column boundary (Compiling, Downloaded, Finished), creating an aligned, easily scannable terminal column4.  
On completion, cargo emits a single-line summary detailing the compilation profile, optimization status, and elapsed duration down to hundredths of a second4.  
A notable drawback in cargo is that progress and status output are routed to stderr by default rather than stdout9. While this preserves stdout for artifact redirection, it causes automated scripts and continuous integration pipelines that inspect stderr for operational issues to mistake informational progress logs for fatal errors10.  
Compiling serde v1.0.197 Compiling bundleup-core v0.1.0 (/work/bundleup) Finished release profile \[optimized\] target(s) in 1.42s

### **Modern JavaScript Runtimes and Bundlers: esbuild, Bun, and Deno**

The JavaScript bundling ecosystem underwent a major performance shift with the release of esbuild, which proved that compilation and bundling could execute in milliseconds rather than minutes3. Written in Go, esbuild features zero CLI parser overhead and summarizes output through concise tabular layouts showing target artifact paths, file sizes, and total durations3.  
Its defaults prioritize common workflows, eliminating configuration files for straightforward tasks3. Runtimes such as Deno and Bun extend this architectural philosophy by consolidating runtimes, package managers, test runners, and bundlers into single binary executables.  
However, esbuild defaults to browser targets; targeting server-side runtimes requires explicit configuration via \--platform=node \--bundle3. Similarly, Bun has historically prioritized rapid feature iteration over CLI interface stability, introducing minor breaking flag changes across releases.  
dist/app.js 142.8kb dist/app.map 312.4kb  
⚡ Done in 18ms

### **GitHub CLI: gh**

The GitHub CLI (gh) exemplifies human and machine co-design in developer tools11. Rather than providing an unconstrained \--json flag that dumps unpredictable payload trees, gh requires the caller to specify the requested keys (for example, gh issue list \--json number,title,author)12. This constraint guarantees schema stability, prevents payload bloat, and safeguards consumer scripts against unexpected API expansions12.  
Furthermore, gh provides built-in stream filtering using \--jq and output formatting via Go templates (-t, \--template), allowing complex scripting without external dependencies12. When attached to an interactive terminal, gh routes long outputs through an internal pager; when piped to another process, it outputs raw, unpaginated text without terminal escape codes15. The trade-off is increased command verbosity during exploratory terminal usage when a developer simply wants to inspect the entire raw payload12.

### **Version Control and Environment Management: git and pipx**

The design of git established the foundational pattern of separating user-facing porcelain commands from machine-facing plumbing commands. Porcelain commands prioritize interactive readability and terminal ergonomics, while plumbing commands provide strictly formatted, backward-compatible outputs designed for automation.  
However, git suffers from decades of accumulated interface inconsistencies: flags operate differently across subcommands (such as checkout, switch, and restore), argument order is occasionally rigid, and error messages often expose internal storage mechanics.  
In the Python ecosystem, pipx addressed environment isolation by packaging applications into dedicated virtual environments2. Its primary limitation remains execution latency: invoking commands through pipx incurs high startup delays due to repeated Python interpreter launches and virtual environment discovery routines2.

### **Python Tooling Standards: pytest, pypa/build, and httpie**

The Python ecosystem provides contrasting examples of command-line and API architecture. The test runner pytest demonstrates an effective, high-density terminal interface that tracks execution progress via dot-matrix indicators, collapsing into concise summaries in CI environments. It defines a granular exit code hierarchy (0 for all tests passed, 1 for failed tests, 2 for interrupted runs, 3 for internal errors, 4 for command-line usage errors, and 5 for empty test suites).  
Similarly, pypa/build separates its architecture into a dedicated engine library (build.ProjectBuilder) and a thin CLI runner (python \-m build)16. This separation allows external packaging tools to integrate its build logic in-process without spawning subprocesses or parsing terminal text16.  
In contrast, pip explicitly deprecated and dropped support for its internal Python API8. Because pip was architected assuming complete ownership of the process—mutating global loggers, setting up process-wide configurations, and calling sys.exit() directly—programmatic callers experienced memory leaks, crashes, and state corruption8. This design decision has forced Python tooling to invoke pip exclusively via subprocesses for over a decade8.  
Lastly, httpie illustrates human-first CLI ergonomics through automatic syntax highlighting, formatted JSON output, and intuitive key-value flag syntax, while automatically stripping ANSI codes and formatting when redirected to non-terminal streams.

### **Command Line Interface Guidelines (clig.dev)**

The consensus gathered in clig.dev codifies fundamental UNIX design principles for modern environments5. The guidelines prioritize human readability by default while mandating structured formats (--json) for automation5. Output should convey sufficient status to prevent the appearance of hanging without flooding the terminal with internal logs5.  
Interactive prompts must be avoided whenever stdin is not a terminal, and standard streams must maintain strict boundaries: stdout is reserved for primary data artifacts, while stderr is reserved for operational logs, diagnostics, and progress updates5.

## **Command Line Interface Architecture**

The command-line interface for bundleup must deliver immediate utility for simple packaging tasks while offering granular control for complex deployment targets.

### **Command Hierarchy and Argument Mechanics**

The core responsibility of bundleup is converting a locked Python project into a single executable artifact. Following the model of esbuild and cargo, the root command executes this primary action directly without intermediate subcommands3. Running bundleup without arguments bundles the project in the current working directory using defaults extracted from pyproject.toml.  
Subcommands are reserved strictly for auxiliary lifecycles that diverge from the main packaging flow:

* bundleup check: Validates that lockfiles match declared dependencies, target ABIs exist as pre-built wheels, and platform constraints are met without generating an output binary.  
* bundleup target list: Enumerates available deployment targets (such as lambda, portable, or distroless) and displays their underlying architecture tags.  
* bundleup cache \[dir|clean\]: Inspects and purges the shared wheel and artifact cache directories.

The command interface accepts at most one positional argument representing the project entrypoint or path (for example, bundleup \[ENTRY\], defaulting to .). If the argument resolves to a specific file (such as src/main.py), it is treated as the executable entrypoint; if it resolves to a directory, bundleup searches for project configuration within that directory.  
Deployment presets are passed using \--target  (for example, \--target lambda). Presets expand into concrete flags, including target Python versions, platform tags, and compression levels. To maintain operational transparency, passing \--verbose or \--dry-run prints the full flag expansion to stderr, enabling developers and automated agents to inspect the underlying configuration.

### **Flag Naming Conventions and Ergonomics**

Flag naming across bundleup maintains consistency with established Python packaging conventions from uv and pip2. Interpreter selection uses \--python (short: \-p), accepting semantic versions, executable names, or absolute file paths2. Dependency integrity flags mirror uv: \--locked verifies that lockfiles match project manifests without updating them, while \--frozen skips network and lockfile freshness checks entirely to maximize CI execution speed2.  
Boolean options must provide explicit negative forms prefixed with \--no- (such as \--minify and \--no-minify, or \--strip and \--no-strip), allowing users to override settings defined in pyproject.toml or environment variables directly from the command line. Flags accepting collections (such as \--platform) must support both repeated declarations and comma-separated arguments:

Bash  
bundleup \--platform linux/x86\_64 \--platform darwin/arm64  
bundleup \--platform linux/x86\_64,darwin/arm64

Single-letter short flags are reserved for high-frequency operations: \-o for \--output, \-p for \--python, \-v for \--verbose, \-q for \--quiet, \-h for \--help, and \-V for \--version.

### **Output for Humans: Progressive Disclosure and Color Handling**

Human-facing output balances operational visibility with low terminal noise5. Emulating cargo and esbuild, bundleup avoids multi-line progress dumps on successful runs3. Clean builds print a single-line summary containing the destination artifact path, binary size in human-readable units (KiB, MiB), and total build duration.  
Long-running operations (such as wheel resolution, downloading, and compression) render an inline spinner to stderr. Once a step completes, the spinner line clears or transitions into an immutable status marker, preventing messy terminal scrollback history.  
Terminal styling complies with the NO\_COLOR standard: if the NO\_COLOR environment variable is defined (regardless of value), ANSI escape codes are omitted. When TERM=dumb or when output is redirected away from an interactive TTY, terminal styling and cursor manipulation are disabled5. Unicode symbols (✔, ✖, 📦) automatically fall back to ASCII characters (\[OK\], \[ERROR\], \*) on non-UTF-8 terminals or legacy consoles.

### **Output for Machines and Autonomous Agents**

Automated systems, continuous integration pipelines, and autonomous AI agents require predictable, parseable output5. To support this, standard streams are strictly partitioned: stdout is reserved for program artifacts or structured machine payloads, while stderr handles informational logs, progress indicators, warnings, and diagnostic errors5.  
When invoked with \--json, bundleup emits a single JSON document to stdout. This payload includes a top-level schema\_version integer to ensure backward compatibility as the schema evolves. Operational logging and progress indicators remain isolated to stderr, preventing JSON parse failures in downstream tools like jq5.  
Interactive confirmation prompts are disabled when stdin is not a TTY or when \--json is active5. Commands requiring destructive actions fail immediately with an explicit error rather than blocking indefinitely waiting for terminal input5.

### **Diagnostic Architecture: "What, Why, Next"**

Error reporting follows the diagnostic structure used by the Rust compiler and uv, organizing errors into three distinct components: what happened, why it happened, and what steps to take next1. Expected operational errors—such as missing wheels, lockfile mismatches, or invalid syntax—never print raw Python stack traces5.  
Instead, the error begins with a clear failure summary (×), followed by an indented causal chain (├─▶, ╰─▶) identifying the specific file, line number, or package dependency involved6. The message concludes with an actionable remediation hint (hint:) providing the exact command or configuration change needed to resolve the issue6. Stack traces are reserved for internal crashes and are displayed only when BUNDLEUP\_DEBUG=1 or \--verbose is provided5.

### **Exit Code Taxonomy**

To ensure reliable orchestration in shell scripts and CI environments, bundleup defines a structured exit code hierarchy18. It avoids generic non-zero exit codes, distinguishing usage errors, operational failures, environment issues, and internal bugs18.

| Exit Code | Constant Name | Meaning | Trigger Scenario |
| :---- | :---- | :---- | :---- |
| 0 | EXIT\_SUCCESS | Execution completed successfully. | Artifact generated and written to disk cleanly. |
| 1 | EXIT\_BUILD\_FAILURE | Operational packaging or build failure. | Compilation failed; dependency resolution conflict. |
| 2 | EXIT\_USAGE\_ERROR | Command-line parse or flag validation failure18. | Unknown flag provided; missing value for option21. |
| 3 | EXIT\_CONFIG\_ERROR | Configuration file parsing failure. | Malformed TOML syntax in pyproject.toml. |
| 4 | EXIT\_ENVIRONMENT\_ERROR | Missing host toolchain or system prerequisite. | Target requires clang, but no compiler exists on \$PATH. |
| 70 | EXIT\_SOFTWARE\_BUG | Unhandled internal exception (EX\_SOFTWARE)20. | Internal runtime panic or unexpected library bug. |
| 130 | EXIT\_INTERRUPTED | Execution interrupted via SIGINT (Ctrl+C)20. | Process aborted by developer during execution. |

### **Configuration Precedence and Environmental Control**

Configuration settings resolve down a strict hierarchy, where each tier overrides all subsequent layers:

> 1. Command-Line Interface (CLI) Flags: Explicit runtime options (e.g., \--output dist/app.pyz).  
> 2. Environment Variables: Variables prefixed with BUNDLEUP\_ (e.g., BUNDLEUP\_OUTPUT=dist/app.pyz).  
> 3. Project Configuration: Settings declared in the \[tool.bundleup\] table of ./pyproject.toml.  
> 4. User Configuration: Global settings defined at \~/.config/bundleup/config.toml (or platform equivalent).  
> 5. System Defaults: Hardcoded engine defaults.

Transient flags such as \--dry-run, \--verbose, \--quiet, \--help, and \--version are scoped exclusively to CLI invocations and must never be read from configuration files.

| Configuration Tier | Example Syntax | Scope and Purpose |
| :---- | :---- | :---- |
| **1\. CLI Flags** | bundleup \-p 3.12 \--minify | Invocation-specific overrides. |
| **2\. Environment Variables** | BUNDLEUP\_PYTHON=3.12 | Container, CI environment, or automated agent session. |
| **3\. Project File** | \[tool.bundleup\] in ./pyproject.toml | Shared, version-controlled project configuration. |
| **4\. User Config** | \~/.config/bundleup/config.toml | Developer workstation defaults across projects. |
| **5\. Built-in Defaults** | Internal engine defaults | Standard fallback behaviors. |

### **Discoverability, Documentation, and Startup Budgets**

Terminal help text should fit within standard terminal viewports (80 columns by 24 lines) without excessive scrolling. Options are organized into functional sections: Usage, Arguments, Core Options, Packaging Options, and Output & Diagnostic Options. The footer of \--help contains copy-pasteable invocation examples demonstrating common use cases.  
Reference documentation, manual pages, and shell completion scripts (Bash, Zsh, Fish) are generated directly from the parser definitions during the release build, ensuring documentation stays synchronized with CLI flags.  
CLI responsiveness directly impacts perceived performance. Running bundleup \--help or bundleup \--version must complete within a 15-millisecond budget. Validating project configuration via bundleup check on a warm cache must return within 30 milliseconds.  
To achieve this performance in Python, heavy modules—including zipfile, tarfile, subprocess, urllib, and third-party packages like packaging—must be imported lazily within specific execution paths rather than globally at module initialization23.

### **Deprecation and Evolution Lifecycle**

Breaking changes to command-line flags break CI pipelines and automation scripts. When a flag is retired, it must remain supported across at least two minor release cycles. During this transition, passing the deprecated flag emits a warning to stderr specifying the replacement option and the removal version.  
Similarly, the machine-readable JSON schema includes an integer schema\_version. Minor field additions maintain the existing version, while key removals or structural changes increment the major schema version.

## **Python Library API Design**

To avoid the process-coupling issues that affected pip, bundleup decouples its core packaging logic from the CLI interface8. The command-line utility serves as a thin wrapper over a standalone Python engine library16.

### **Architecture: Engine vs CLI Adapter Separation**

The packaging engine runs statelessly and supports re-entrant execution, ensuring it can run multiple consecutive builds within the same Python process without leaking state8. It never mutates sys.path, never initializes root logging handlers, and handles failures via exceptions rather than calling sys.exit()8.  
The system architecture cleanly separates terminal concerns from packaging mechanics across three primary layers:

* **Presentation Layer (bundleup.cli):** Consumes command-line arguments, evaluates terminal TTY capabilities, handles signal interrupts, formats error diagnostics, and maps exceptions to exit codes18.  
* **Packaging Engine Layer (bundleup.api):** Exposes pure Python functions (build(), check()), accepts frozen option dataclasses, returns immutable result structures, and raises typed exception hierarchies16.  
* **Low-Level Execution Layer (bundleup.core):** Manages zipapp generation, bytecode compilation, dependency resolution via uv, and wheel metadata extraction2.

| Architectural Layer | Permitted Responsibilities | Prohibited Behaviors |
| :---- | :---- | :---- |
| **CLI Adapter Layer (bundleup.cli)** | Parsing sys.argv, configuring terminal colors, drawing progress spinners, formatting error trees, emitting exit codes5. | Direct zip manipulation, raw bytecode generation, core packaging logic. |
| **API Engine Layer (bundleup.api)** | Validating options, coordinating build lifecycles, emitting telemetry, raising domain exceptions8. | Calling sys.exit(), reading sys.argv, printing directly to stdout/stderr, configuring root loggers8. |
| **Core Utilities (bundleup.core)** | File compression, wheel parsing, subprocess execution of uv2. | Direct CLI flag evaluation, high-level user messaging. |

### **Public Library API Specification**

The library exposes its public interface directly from the root bundleup package, defining visible exports using \_\_all\_\_.

Python  
"""Public Python API for the bundleup packaging engine.

This module provides in-process programmatic access to bundleup's  
packaging and verification engine.  
"""

from \_\_future\_\_ import annotations

from dataclasses import dataclass, field  
from pathlib import Path  
from typing import Final, Literal, Mapping, Sequence

\_\_all\_\_ \= \[  
    "BundleOptions",  
    "BundleResult",  
    "ArtifactMetadata",  
    "TimingMetrics",  
    "build",  
    "check",  
    "BundleupError",  
    "LockfileOutOfSyncError",  
    "PlatformIncompatibleError",  
    "BuildBackendExecutionError",  
    "ConfigurationError",  
\]

\# \---------------------------------------------------------------------------  
\# Exception Hierarchy  
\# \---------------------------------------------------------------------------

class BundleupError(Exception):  
    """Base exception for all errors raised by the bundleup packaging engine."""  
    def \_\_init\_\_(self, message: str, \*, hint: str | None \= None) \-\> None:  
        super().\_\_init\_\_(message)  
        self.message: Final\[str\] \= message  
        self.hint: Final\[str | None\] \= hint

class LockfileOutOfSyncError(BundleupError):  
    """Raised when dependencies in pyproject.toml do not match the lockfile."""

class PlatformIncompatibleError(BundleupError):  
    """Raised when requested dependencies lack wheels for the target ABI/platform."""

class BuildBackendExecutionError(BundleupError):  
    """Raised when an external PEP 517 build backend fails to build a wheel."""  
    def \_\_init\_\_(  
        self,  
        message: str,  
        \*,  
        backend\_name: str,  
        exit\_code: int,  
        stderr\_output: str,  
        hint: str | None \= None,  
    ) \-\> None:  
        super().\_\_init\_\_(message, hint=hint)  
        self.backend\_name: Final\[str\] \= backend\_name  
        self.exit\_code: Final\[int\] \= exit\_code  
        self.stderr\_output: Final\[str\] \= stderr\_output

class ConfigurationError(BundleupError):  
    """Raised when project or options configuration is malformed or invalid."""

\# \---------------------------------------------------------------------------  
\# Options and Return Data Structures  
\# \---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)  
class BundleOptions:  
    """Configuration options for a bundling operation."""  
    entrypoint: Path | str \= "."  
    output\_path: Path \= field(default\_factory=lambda: Path("dist/app.pyz"))  
    target\_preset: str | None \= None  
    python\_version: str | None \= None  
    platforms: Sequence\[str\] \= field(default\_factory=tuple)  
    locked: bool \= False  
    frozen: bool \= False  
    minify: bool \= False  
    strip\_debug: bool \= True  
    compression: Literal\["none", "deflate", "zstd"\] \= "deflate"  
    extra\_metadata: Mapping\[str, str\] \= field(default\_factory=dict)

@dataclass(frozen=True, slots=True)  
class ArtifactMetadata:  
    """Metadata describing the generated binary artifact."""  
    path: Path  
    size\_bytes: int  
    sha256: str  
    entrypoint: str  
    python\_requires: str  
    target\_platform: str  
    packages\_bundled: int

@dataclass(frozen=True, slots=True)  
class TimingMetrics:  
    """Execution timing profile in milliseconds."""  
    resolve\_duration\_ms: int  
    pack\_duration\_ms: int  
    total\_duration\_ms: int

@dataclass(frozen=True, slots=True)  
class BundleResult:  
    """The successful result returned by a packaging execution."""  
    artifact: ArtifactMetadata  
    metrics: TimingMetrics  
    warnings: Sequence\[str\] \= field(default\_factory=tuple)

\# \---------------------------------------------------------------------------  
\# Primary Engine Entrypoints  
\# \---------------------------------------------------------------------------

def build(options: BundleOptions | None \= None, \*\*overrides: object) \-\> BundleResult:  
    """Compile a locked Python project into a self-contained executable.

    Parameters:  
        options: A fully configured BundleOptions instance.  
        \*\*overrides: Individual option overrides applied on top of options.

    Returns:  
        A BundleResult containing metadata, timing, and artifact metrics.

    Raises:  
        BundleupError: Or one of its subclasses if packaging fails.  
    """  
    ...

def check(options: BundleOptions | None \= None) \-\> Sequence\[str\]:  
    """Validate project integrity, lockfile synchronization, and wheel availability.

    Returns:  
        A sequence of warning messages, if any. Returns an empty sequence if valid.

    Raises:  
        BundleupError: If validation fails critically.  
    """  
    ...

## **Implementation Engineering: Frameworks, Styling, and Testing**

Achieving the sub-15 millisecond CLI startup target in Python requires minimizing module import overhead. Because Python imports modules synchronously, dependencies loaded at startup directly increase command execution latency.

### **CLI Framework Evaluation**

Selecting a CLI framework requires balancing startup latency, dependency footprint, help formatting quality, and type validation.

| Framework | Cold-Start Import Overhead | External Dependencies | Help Customization | Type-Hint Integration |
| :---- | :---- | :---- | :---- | :---- |
| **argparse** | **0.00 ms** (Standard Library)23 | **None** (Built-in) | Basic (rigid wrapping, hard to group) | None (runtime strings and manually configured converters) |
| **Click** | \~18.00–24.00 ms | Base (click) | High (custom formatters supported) | Limited (decorator-heavy, untyped internals) |
| **Typer** | \~42.00–65.00 ms | Heavy (click, typing\_extensions, optional rich) | High (Rich terminal output built-in) | Native (function signatures drive arguments) |
| **Cyclopts** | \~12.00–16.00 ms | Moderate (attrs/pydantic, docstring\_parser) | High (clean layouts, built-in grouping)21 | Native (fully type-driven, supports modern Python unions)24 |

While typer provides modern type-driven argument parsing, its dependency chain (click, typing\_extensions, and rich) introduces 42 to 65 milliseconds of cold-start latency, making it impossible to meet a 15-millisecond target for \--help or \--version.  
Standard library argparse incurs zero import overhead and adds no dependencies, but its help formatting is rigid and it lacks type-hint integration23. Cyclopts offers a compelling compromise by deriving CLI arguments directly from type hints with roughly 12 to 16 milliseconds of startup overhead24.  
To maintain strict performance guarantees, bundleup implements a **two-tier execution architecture**. Fast-path commands (--help, \--version, and argument parsing) run through a hand-rolled parser or standard argparse with a customized HelpFormatter23. If rich terminal layouts or complex subcommand routing are needed, execution lazily hands off to dedicated command handlers. Given that bundleup already vendor-isolates packaging and interfaces with uv, avoiding heavy runtime dependencies keeps the tool lean and responsive2.

### **Terminal Styling: Rich vs Lightweight ANSI**

The rich library produces polished terminal interfaces, but importing it incurs a 30 to 50 millisecond overhead while loading modules like pygments and markdown25. This import penalty alone exceeds the total startup budget for bundleup.  
Instead, bundleup uses a lightweight internal ANSI helper module requiring under 50 lines of code. It adds zero external dependencies and imports in less than 0.05 milliseconds.

Python  
\# Internal ANSI terminal styling helper (bundleup.\_term)  
import os  
import sys

\_NO\_COLOR: bool \= bool(os.environ.get("NO\_COLOR"))  
\_IS\_TTY: bool \= sys.stderr.isatty() and os.environ.get("TERM") \!= "dumb"

def style(text: str, code: str) \-\> str:  
    if \_NO\_COLOR or not \_IS\_TTY:  
        return text  
    return f"\\033\[{code}m{text}\\033\[0m"

def bold(text: str) \-\> str: return style(text, "1")  
def green(text: str) \-\> str: return style(text, "32")  
def red(text: str) \-\> str: return style(text, "31")  
def yellow(text: str) \-\> str: return style(text, "33")  
def dim(text: str) \-\> str: return style(text, "2")

This helper handles color toggling, respects NO\_COLOR, checks TTY status, and runs with negligible import cost5. Progress indicators are implemented using standard carriage returns (\\r) written directly to stderr.

### **CLI Testing Architecture and Automation**

Testing CLI behavior requires verifying standard stream separation, asserting exit codes, and confirming formatting across simulated terminal environments. Tests should run in isolated subprocesses to capture real import overhead and verify behavior across different environment configurations.

Python  
"""Automated CLI test suite verifying terminal output and stream separation."""

import json  
import subprocess  
import sys  
import pytest

@pytest.fixture  
def run\_cli():  
    """Execute bundleup CLI as an isolated external process."""  
    def \_run(args: list\[str\], env\_overrides: dict\[str, str\] | None \= None):  
        cmd \= \[sys.executable, "-m", "bundleup.cli", \*args\]  
        env \= {  
            "PATH": sys.path\[0\],  
            "NO\_COLOR": "1",  \# Strip color sequences during assertions  
            \*\*(env\_overrides or {})  
        }  
        return subprocess.run(  
            cmd,  
            stdout=subprocess.PIPE,  
            stderr=subprocess.PIPE,  
            text=True,  
            env=env,  
        )  
    return \_run

def test\_help\_startup\_budget(run\_cli):  
    """Assert help text displays cleanly and returns exit code 0."""  
    res \= run\_cli(\["--help"\])  
    assert res.returncode \== 0  
    assert "Usage: bundleup" in res.stdout  
    assert res.stderr \== ""  \# Help text must not leak to stderr

def test\_stream\_separation\_with\_json(run\_cli, tmp\_path):  
    """Ensure machine output routes exclusively to stdout with valid JSON schema."""  
    target\_out \= tmp\_path / "bundle.pyz"  
    res \= run\_cli(\["--output", str(target\_out), "--json"\])  
    assert res.returncode \== 0  
      
    \# stdout must parse cleanly as a structured JSON object  
    data \= json.loads(res.stdout)  
    assert data\["schema\_version"\] \== 1  
    assert data\["status"\] \== "success"  
    assert "artifact" in data

    \# stderr should contain no JSON payloads  
    assert "{" not in res.stderr

def test\_usage\_error\_exit\_code(run\_cli):  
    """Invalid command line arguments must exit with code 2."""  
    res \= run\_cli(\["--invalid-flag"\])  
    assert res.returncode \== 2  
    assert "error:" in res.stderr.lower() or "unrecognized arguments" in res.stderr.lower()

def test\_no\_color\_compliance(run\_cli):  
    """Assert ANSI color escape codes are completely omitted when NO\_COLOR is provided."""  
    res \= run\_cli(\["--help"\], env\_overrides={"NO\_COLOR": "1"})  
    assert "\\033\[" not in res.stdout  
    assert "\\033\[" not in res.stderr

## **The bundleup Style Guide**

The following numbered rules establish the implementation standards for bundleup across its command-line interface and Python library API.

### **Command Line Interface Rules**

> 1. **Rule CLI-01: Default to the primary action at the root.**  
   * *Rationale:* Developers should not be forced to type redundant subcommands for the tool's core operation3.  
   * *Example:* Run bundleup instead of bundleup build.  
> 2. **Rule CLI-02: Reserve subcommands for distinct lifecycle boundaries.**  
   * *Rationale:* Subcommands must represent distinct verbs that diverge from the main compilation workflow.  
   * *Example:* Use bundleup check and bundleup cache clean.  
> 3. **Rule CLI-03: Accept at most one positional argument.**  
   * *Rationale:* Multiple positional arguments with distinct semantics create parsing ambiguity and confuse users5.  
   * *Example:* Accept bundleup \[ENTRY\], where entry defaults to ..  
> 4. **Rule CLI-04: Show expanded preset options when requested.**  
   * *Rationale:* Presets must not obscure underlying tool mechanics from developers or agents.  
   * *Example:* When \--dry-run is passed, \--target lambda logs its resolution: expanded: \--python 3.12 \--platform manylinux2014\_x86\_64.  
> 5. **Rule CLI-05: Maintain flag parity with packaging standards.**  
   * *Rationale:* Consistency with tools like uv and pip aligns with existing muscle memory and packaging conventions2.  
   * *Example:* Use \--python, \--locked, and \--frozen with matching semantics2.  
> 6. **Rule CLI-06: Pair every boolean flag with a negative inverse.**  
   * *Rationale:* Users must be able to negate options set in pyproject.toml or environment variables directly from the CLI.  
   * *Example:* Provide both \--minify and \--no-minify.  
> 7. **Rule CLI-07: Reserve single-letter flags for the most common operations.**  
   * *Rationale:* Over-allocating short flags exhausts intuitive single-letter names and clutters the CLI namespace5.  
   * *Example:* Use short flags only for \-o, \-p, \-v, \-q, \-h, and \-V.  
> 8. **Rule CLI-08: Support both repeated flags and comma separation for lists.**  
   * *Rationale:* Accommodates different shell scripting preferences and argument-passing paradigms.  
   * *Example:* Allow both \--platform linux \--platform darwin and \--platform linux,darwin.  
> 9. **Rule CLI-09: Provide zero-config defaults from the local project context.**  
   * *Rationale:* Tools must inspect the local repository and infer sensible defaults without requiring manual boilerplate.  
   * *Example:* Running bundleup automatically detects the lockfile and entry point defined in pyproject.toml.  
> 10. **Rule CLI-10: Emit human-facing success in three or fewer lines.**  
    * *Rationale:* Successful builds should not drown the terminal in unrequested output5.  
    * *Example:* Print ✔ Built dist/app (1.4 MiB) in 24ms.  
> 11. **Rule CLI-11: Clear ephemeral progress indicators on terminal exit.**  
    * *Rationale:* Animated spinners must not leave behind messy lines in scrollback history.  
    * *Example:* Erase the spinner line or replace it with an immutable completion summary once the step finishes.  
> 12. **Rule CLI-12: Comply strictly with NO\_COLOR and non-TTY checks.**  
    * *Rationale:* Unescaped ANSI control characters corrupt CI logs and break downstream processing pipelines5.  
    * *Example:* If os.environ.get("NO\_COLOR") is set, emit plain text without ANSI escape sequences.  
> 13. **Rule CLI-13: Silence all informational messages when \--quiet is set.**  
    * *Rationale:* Automation pipelines require a mode that runs silently unless an error occurs.  
    * *Example:* When \-q is active, emit nothing on success and print only errors to stderr.  
> 14. **Rule CLI-14: Isolate machine data to stdout and operational logs to stderr.**  
    * *Rationale:* Mixing diagnostic output into stdout corrupts data when piping into utilities like jq5.  
    * *Example:* Send \--json output to stdout; send progress, logs, and hints to stderr5.  
> 15. **Rule CLI-15: Include an integer schema\_version in all JSON payloads.**  
    * *Rationale:* Prevents automated tools and agents from breaking as the output payload evolves.  
    * *Example:* Include "schema\_version": 1 as the root field in all JSON output.  
> 16. **Rule CLI-16: Never prompt in automated, piped, or non-TTY environments.**  
    * *Rationale:* Interactive prompts cause automated builds, CI pipelines, and agent loops to hang indefinitely5.  
    * *Example:* Fail immediately with an actionable error if confirmation is required without a TTY.  
> 17. **Rule CLI-17: Format errors using the "What, Why, Next" structure.**  
    * *Rationale:* Developers need to understand the problem, its source, and how to fix it without parsing raw stack traces5.  
    * *Example:* Structure errors with an error: line, a Caused by: chain, and an actionable hint:6.  
> 18. **Rule CLI-18: Suppress tracebacks for operational failures.**  
    * *Rationale:* Expected domain errors are not internal tool bugs; displaying tracebacks reduces signal-to-noise5.  
    * *Example:* Print a structured diagnostic on missing dependencies; show tracebacks only when BUNDLEUP\_DEBUG=1 is set5.  
> 19. **Rule CLI-19: Document and adhere to a strict exit code taxonomy.**  
    * *Rationale:* Automation scripts rely on consistent exit codes to distinguish usage errors from build failures18.  
    * *Example:* Return exit code 2 for invalid CLI flags and 1 for build errors18.  
> 20. **Rule CLI-20: Maintain a predictable configuration precedence order.**  
    * *Rationale:* Developers need clear rules for how flag overrides interact with environment variables and config files.  
    * *Example:* Resolve settings in order: CLI flags \> environment variables \> pyproject.toml \> defaults.  
> 21. **Rule CLI-21: Prefix all environment variables with BUNDLEUP\_.**  
    * *Rationale:* Prevents collisions with other tools or system-level environment variables.  
    * *Example:* Use BUNDLEUP\_PYTHON rather than PYTHON\_VERSION.  
> 22. **Rule CLI-22: Group options logically within \--help.**  
    * *Rationale:* Grouped options make help menus easier to scan than long alphabetical lists.  
    * *Example:* Separate options into Core Options, Packaging Options, and Output Options.  
> 23. **Rule CLI-23: Include real-world invocation examples in \--help.**  
    * *Rationale:* Concrete examples allow developers to understand usage patterns without consulting web docs.  
    * *Example:* Include examples like bundleup \--target lambda \-o handler.zip at the bottom of the help text.  
> 24. **Rule CLI-24: Maintain a startup latency under 15 milliseconds.**  
    * *Rationale:* Tools that feel instant encourage frequent local execution and improve workflow responsiveness.  
    * *Example:* Run bundleup \--version in ![][image1] by lazily loading packaging modules23.  
> 25. **Rule CLI-25: Warn before deprecating flags across two minor versions.**  
    * *Rationale:* Gives users and CI maintainers time to update scripts before breaking changes take effect.  
    * *Example:* Print warning: \--dest is deprecated; use \--output instead (will be removed in v1.2.0) to stderr.

### **Python Library API Rules**

> 26. **Rule API-01: Decouple the packaging engine from CLI logic.**  
    * *Rationale:* The core library should never inspect command-line arguments, read sys.argv, or depend on terminal frameworks8.  
    * *Example:* Isolate the engine in bundleup.api and keep the CLI wrapper in bundleup.cli.  
> 27. **Rule API-02: Never invoke sys.exit() or mutate global logging inside library code.**  
    * *Rationale:* Library calls must not terminate the host process or overwrite application-wide logger settings8.  
    * *Example:* Raise a BundleupError subclass instead of calling sys.exit(1)8.  
> 28. **Rule API-03: Expose high-level operations as pure Python functions.**  
    * *Rationale:* Common operations should be accessible via clean, single-function entry points16.  
    * *Example:* Expose bundleup.build(options: BundleOptions) \-\> BundleResult16.  
> 29. **Rule API-04: Accept typed, frozen options and return immutable result objects.**  
    * *Rationale:* Immutable, typed data structures prevent unexpected parameter mutation and improve IDE autocompletion.  
    * *Example:* Use @dataclass(frozen=True) for BundleOptions and BundleResult.  
> 30. **Rule API-05: Inherit all exceptions from a base BundleupError.**  
    * *Rationale:* Allows calling applications to catch all library-specific exceptions with a single except block.  
    * *Example:* Define class BundleupError(Exception): pass and derive all package errors from it.  
> 31. **Rule API-06: Explicitly declare the public API via \_\_all\_\_.**  
    * *Rationale:* Prevents internal helper functions and implementation details from being accidentally consumed by external packages.  
    * *Example:* Define \_\_all\_\_ \= \["build", "check", "BundleOptions", "BundleResult", "BundleupError"\] in the root \_\_init\_\_.py.  
> 32. **Rule API-07: Make the CLI a thin, zero-logic adapter over the Python API.**  
    * *Rationale:* Avoids diverging behaviors between terminal runs and programmatic invocations16.  
    * *Example:* The CLI parser should simply populate BundleOptions, call build(), and format the resulting BundleResult.

## **Concrete CLI and Schema Deliverables**

The following mockups illustrate terminal renderings for human developers alongside structured JSON payloads designed for machine parsing and agent interactions.

### **1\. Successful Build Output (Human TTY)**

\$ bundleup \--target lambda \-o dist/handler.pyz Resolving dependencies from uv.lock... (41 packages) Bundling dist/handler.pyz \[manylinux2014\_x86\_64, Python 3.12\] ✔ Built dist/handler.pyz (1.82 MiB) in 28ms

### **2\. Build with Warnings (Human TTY)**

\$ bundleup \-o dist/app.pyz Resolving dependencies from uv.lock... (18 packages) Bundling dist/app.pyz \[any, Python 3.11\] warning: Package pydantic-core contains native extensions but target platform is any Executable may fail when transferred to different OS architectures. hint: Pass \--platform  (e.g. \--platform linux/x86\_64) to bundle compatible wheels. ✔ Built dist/app.pyz (4.12 MiB) with 1 warning in 42ms

### **3\. Error Case 1: Lockfile Out of Sync**

\$ bundleup \--locked × Lockfile verification failed ├─▶ Project dependencies in pyproject.toml do not match uv.lock ╰─▶ Missing locked entry for requirement: httpx\>=0.27.0  
hint: Run uv lock or bundleup lock to update the lockfile, or drop \--locked to allow updates.

### **4\. Error Case 2: Incompatible Platform ABI**

\$ bundleup \--platform musllinux\_1\_2\_aarch64 × Target platform incompatible with available wheels ├─▶ Failed to locate compatible binary distribution for cryptography==42.0.5 ╰─▶ Pre-compiled wheel not found for platform tag: musllinux\_1\_2\_aarch64 Source distribution is available, but C toolchain (musl-gcc) is missing from host.  
hint: Install a compatible cross-compiler or specify an alternate platform target.

### **5\. Error Case 3: Subprocess Build Backend Failure**

\$ bundleup × Failed to build distribution from source: orjson==3.9.15 ├─▶ The PEP 517 build backend returned an exit status: 1 ╰─▶ Call to maturin.build\_wheel failed \[stderr\] error: cargo not found in PATH. Building orjson from source requires a Rust toolchain.  
hint: Install Rust from https\://rustup.rs/ or configure pre-built wheels for your environment.

### **6\. Structured Machine Output (bundleup \--json)**

JSON  
{  
  "\$schema": "https\://bundleup.dev/schemas/v1/build-result.json",  
  "schema\_version": 1,  
  "status": "success",  
  "artifact": {  
    "path": "/work/project/dist/app.pyz",  
    "name": "app.pyz",  
    "size\_bytes": 1912420,  
    "sha256": "8f4e2c6081e649b5832a82df4b14e6b2084c8a2ef37d427d142171c6d36e2f18"  
  },  
  "metadata": {  
    "entrypoint": "app.cli:main",  
    "python\_requires": "\>=3.11",  
    "target\_platform": "manylinux2014\_x86\_64",  
    "compression": "zstd",  
    "packages\_bundled": 42  
  },  
  "metrics": {  
    "duration\_ms": 31,  
    "resolve\_duration\_ms": 9,  
    "pack\_duration\_ms": 22  
  },  
  "warnings": \[\]  
}

### **7\. Discoverability Output (bundleup \--help)**

Turn locked Python projects into single, high-performance executables.  
Usage: bundleup \[ENTRY\] \[OPTIONS\]  
Arguments: \[ENTRY\] Application entrypoint script or module \[default: .\]  
Core Options: \-o, \--output Output path for the generated bundle \[default: dist/app.pyz\] \--target Preconfigured deployment target: lambda, portable, distroless \--dry-run Simulate build steps and print configuration without packaging  
Packaging Options: \-p, \--python Target Python version specification \[default: host\] \--platform Target platform tag (e.g. manylinux2014\_x86\_64) \[repeatable\] \--locked Assert lockfile is up to date; exit with error if changes exist \--frozen Build strictly from lockfile without refreshing metadata \--minify / \--no-minify Strip docstrings and run internal bytecode optimizer \[default: no\]  
Output & Diagnostic Options: \-q, \--quiet Suppress non-error output \-v, \--verbose Enable verbose logging (-v: debug info, \-vv: trace steps) \--json Emit structured build result as JSON to stdout \--no-color Disable ANSI styling (respects NO\_COLOR env var) \-h, \--help Show this help message and exit \-V, \--version Show bundleup version information and exit  
Examples: \$ bundleup \# Bundle project using defaults from pyproject.toml \$ bundleup \-o dist/api.pyz \--target lambda \# Bundle using AWS Lambda preset \$ bundleup src/main.py \-p 3.12 \--minify \# Bundle custom script entrypoint with minification \$ bundleup \--json \> result.json \# Emit machine-readable build telemetry for CI/Agents

## **Architectural Synthesis and Framework Recommendation**

Designing a developer tool that feels fast requires keeping cold-start overhead low. For Python applications, import latency is the primary bottleneck: every package loaded during startup directly degrades command response times23.  
A detailed evaluation of the Python ecosystem supports the following architectural decisions:

> 1. **CLI Framework Selection:** Standard library argparse is the recommended option for bundleup's command line layer23. It introduces zero additional dependencies and executes with 0.00 ms import latency23. While its default help output is plain, implementing a custom argparse.HelpFormatter provides clean section grouping, aligned argument columns, and integrated usage examples without adding third-party overhead. While Cyclopts offers clean type-driven interfaces, its 12 to 16 ms startup cost leaves narrow headroom for a 15 ms target budget24. Frameworks such as typer (42–65 ms) and click (18–24 ms) add noticeable startup latency and are not recommended for high-performance packaging tools.  
> 2. **Terminal Styling Implementation:** Heavy terminal rendering libraries such as rich add 30 to 50 ms of module import overhead, pulling in pygments and other formatting dependencies25. bundleup should instead use a lightweight internal ANSI formatting module (under 50 lines of code) that compiles down to raw escape sequences, checks NO\_COLOR and TTY status, and runs in under 0.05 ms5.  
> 3. **Decoupled Architecture:** The command-line interface must remain a thin translation adapter over a standalone, programmatic Python API16. The core packaging engine must never call sys.exit(), inspect sys.argv, or configure process-wide logging8. Isolating build logic into pure functions that accept frozen dataclasses and raise explicit domain exceptions ensures that bundleup remains maintainable, easy to test, and ready for integration into broader automation workflows8.

#### **Works cited**

> 1. Ruff v0.16.0 \- Astral, [https\://astral.sh/blog/ruff-v0.16.0](https://astral.sh/blog/ruff-v0.16.0)  
> 2. uv: Unified Python packaging \- Astral, [https\://astral.sh/blog/uv-unified-python-packaging](https://astral.sh/blog/uv-unified-python-packaging)  
> 3. API \- esbuild, [https\://esbuild.github.io/api/](https://esbuild.github.io/api/)  
> 4. Customizing Builds with Release Profiles \- The Rust Programming, [https\://doc.rust-lang.org/book/ch14-01-release-profiles.html](https://doc.rust-lang.org/book/ch14-01-release-profiles.html)  
> 5. Command Line Interface Guidelines, [https\://clig.dev/](https://clig.dev/)  
> 6. Build failures | uv \- Astral Docs, [https\://docs.astral.sh/uv/reference/troubleshooting/build-failures/](https://docs.astral.sh/uv/reference/troubleshooting/build-failures/)  
> 7. \[Error\] uv pip install \-e . · Issue \#4954 · astral-sh/uv \- GitHub, [https\://github.com/astral-sh/uv/issues/4954](https://github.com/astral-sh/uv/issues/4954)  
> 8. User Guide \- pip documentation v26.2.1, [https\://pip.pypa.io/en/stable/user\_guide/](https://pip.pypa.io/en/stable/user_guide/)  
> 9. Console output should better reflect the build process \#8889 \- GitHub, [https\://github.com/rust-lang/cargo/issues/8889](https://github.com/rust-lang/cargo/issues/8889)  
> 10. How to get rid of Cargo's "Finished", "Compiling", "Building ... \- Reddit, [https\://www\.reddit.com/r/rust/comments/zl7sct/how\_to\_get\_rid\_of\_cargos\_finished\_compiling/](https://www.reddit.com/r/rust/comments/zl7sct/how_to_get_rid_of_cargos_finished_compiling/)  
> 11. gh formatting help \- GitHub CLI | Take GitHub to the command line, [https\://cli.github.com/manual/gh\_help\_formatting](https://cli.github.com/manual/gh_help_formatting)  
> 12. gh reference \- GitHub CLI, [https\://cli.github.com/manual/gh\_help\_reference](https://cli.github.com/manual/gh_help_reference)  
> 13. gh discussion view \- GitHub CLI, [https\://cli.github.com/manual/gh\_discussion\_view](https://cli.github.com/manual/gh_discussion_view)  
> 14. gh project item-create \- GitHub CLI, [https\://cli.github.com/manual/gh\_project\_item-create](https://cli.github.com/manual/gh_project_item-create)  
> 15. gh repo read-file \- GitHub CLI, [https\://cli.github.com/manual/gh\_repo\_read-file](https://cli.github.com/manual/gh_repo_read-file)  
> 16. API Documentation \- build \- 1.6.1, [https\://build.pypa.io/en/stable/reference/api.html](https://build.pypa.io/en/stable/reference/api.html)  
> 17. Basic Usage \- build \- 1.6.1, [https\://build.pypa.io/en/latest/how-to/basic-usage.html](https://build.pypa.io/en/latest/how-to/basic-usage.html)  
> 18. Create Cli by antoniolg — AI Skill for Any LLM | TypingMind, [https\://www\.typingmind.com/skills/antoniolg-create-cli](https://www.typingmind.com/skills/antoniolg-create-cli)  
> 19. nav-pilot: Tier 1 CLI quality gaps (clig.dev compliance) \#197 \- GitHub, [https\://github.com/navikt/copilot/issues/197](https://github.com/navikt/copilot/issues/197)  
> 20. Understanding Bash Exit Codes | PDF | Command Line Interface | C++, [https\://www\.scribd.com/document/432518494/Exit-Codes-With-Special-Meanings-of-unux](https://www.scribd.com/document/432518494/Exit-Codes-With-Special-Meanings-of-unux)  
> 21. Releases · BrianPugh/cyclopts \- GitHub, [https\://github.com/BrianPugh/cyclopts/releases](https://github.com/BrianPugh/cyclopts/releases)  
> 22. Shell Scripting Standards \- SQLServerCentral, [https\://www\.sqlservercentral.com/articles/shell-scripting-standards](https://www.sqlservercentral.com/articles/shell-scripting-standards)  
> 23. [unknown\_url](http://docs.google.com/unknown_url)  
> 24. cyclopts · PyPI, [https\://pypi.org/project/cyclopts/3.0.1/](https://pypi.org/project/cyclopts/3.0.1/)  
> 25. \[Improvement\] progress.track is relatively slow · Issue \#176 \- GitHub, [https\://github.com/Textualize/rich/issues/176](https://github.com/Textualize/rich/issues/176)  
> 26. willmcgugan/rich Rich is a Python library for rich text and beautiful, [https\://www\.reddit.com/r/Python/comments/kcyg3o/willmcguganrich\_rich\_is\_a\_python\_library\_for\_rich/](https://www.reddit.com/r/Python/comments/kcyg3o/willmcguganrich_rich_is_a_python_library_for_rich/)

[image1]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEkAAAAZCAYAAAB9/QMrAAADBElEQVR4Xu2XWahNURjH/2bKTAjRFZEiD+bxoozlCQ8kEQ9CIi+SOQ+EpMx0j1IUCUkkyfggHpAo6kaGEjKkJOH/v99e3XVWZ+/2vQfd092/+tU56/vOXnt/a6/hABkZGRn1i4Z0Ae0WBkhPuoKOoi1pGZ1N5/lJpURbupbepM2DWCEW01P0A/1Nh+SHqxgPi/m+psP9pFKgC91Gb9O5tFF+OJbldDrdifgildNX9C49DxsE9Vcy9KL76TU6gzbID6dmDeKLNJbmwsZSYAA9Ti/CpkOxJBVpDGpepI50GJ1Ge8MGrz+dAlsSHHqOqbSV1+bQb8bRpXQkLK9ZXkYMI+g5epoODmLFkFSk0bA+99Cr9D6scEloE3gBu+YmepZuocfod9hD6/MhupF+o3P0w4j29BGdTyfSw7BrqfiJqKo/6KIw8BdIKpIG5iOqB6UvfQdbm5LoDrumitIjatMu+hb2HLOiNnGGPvG+azdVYR16qyqRokiiDz1Cr9DJQawYXJGGhgHSAnYM8KmgP2FTKQ5NK13zZND+GPaWqWCOg7Bcxzr6i+6mE2hT2g/pN6QqdJ7ZRa/TmcjvsDa4ImkdScNWWP7CMODRGpazI2jXNLoTtGnz8YvUjt6I2uRXutKL14gOsDmtTrUONMmLpiepSLfoPeQPxGZY/jKvLUSLsXJ0NPF5ALumz15Yrtud9eaoP73ZureHUbw8itcKnYRXwYqlG09zkPRxRQoPiLppHRyf0sZe+wFYvk7hcbRB4SLpgXWe89kHy3UDcRS2YDvUdyVsEygajYAWdh0N9DktG2A3OSkMkO2wrdyhteYlvey1FaIr7Jp6S3xUcO2Q/pupdVa5GmyRoxdQnaPBeg5bWv47l2Cdf6KfYXP/GV3v5eh0ra0/Byum1hQNQicvJ2Q17K/OF9g1tVBrAdbboDb5Jmpz/avtPV0C60vHnArYv4ETsMFy07HOop1VZ5lBYeAf0Nn7XOhPdyyaPrrRNJZFv6l3DISdPNOohdBfaDMyMjIyMuoWfwDU7KdQAyFEYAAAAABJRU5ErkJggg==>