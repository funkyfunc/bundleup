# bundleup: lets processes a bundle starts with its own interpreter see its packages (ADR-0027).
#
# Copied into every .pyz payload as __bundleup__/sitecustomize.py. The bundle puts that directory
# (and only it) on PYTHONPATH, so every Python its program starts imports this file at start-up:
# - the bundle's own interpreter (same sys.prefix, version and ABI) running the bundle's code
#   (`sys.executable -c ...`, multiprocessing, `-m` of a bundled module) activates the bundle, as
#   the loader did in the parent;
# - anything else is left alone: another venv, version or build of Python, and also a tool
#   installed with the same Python (a console script), whose own packages activation would hide.
# Either way, the sitecustomize that Python would otherwise have imported still runs.
# Imported by arbitrary Python 3 versions, so it uses the loader's syntax rules (no f-strings).
import os
import sys


def _bundleup_child() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    norm = os.path.normcase(here)
    sys.path[:] = [p for p in sys.path if os.path.normcase(os.path.abspath(p or ".")) != norm]
    site = os.path.dirname(here)
    active = os.environ.get("BUNDLEUP_RUNTIME_SITE", "")
    if active and os.path.normcase(os.path.abspath(active)) == os.path.normcase(site):
        sys.path.insert(0, here)
        try:
            import _bundleup_runtime  # type: ignore[import-not-found]  # payload module
        finally:
            del sys.path[0]
        same_python = _bundleup_runtime.identity() == os.environ.get(_bundleup_runtime.ENV_PYTHON)
        if same_python and _bundleup_runtime.runs_bundle_code(site):
            _bundleup_runtime.activate(site)
    _chain(here)


def _chain(here: str) -> None:
    """Import the sitecustomize this file shadows, as Python would have without the bundle."""
    try:
        import importlib.util
        from importlib.machinery import PathFinder
    except ImportError:
        return
    norm = os.path.normcase(here)
    paths = [p for p in sys.path if os.path.normcase(os.path.abspath(p or ".")) != norm]
    spec = PathFinder.find_spec("sitecustomize", paths)
    exec_module = getattr(spec.loader, "exec_module", None) if spec else None
    if spec is None or exec_module is None:
        return
    module = importlib.util.module_from_spec(spec)
    sys.modules["sitecustomize"] = module
    try:
        exec_module(module)
    except Exception as e:  # what site.py does when sitecustomize fails
        sys.stderr.write("Error in sitecustomize; set PYTHONVERBOSE for traceback:\n")
        sys.stderr.write("%s: %s\n" % (type(e).__name__, e))


_bundleup_child()
