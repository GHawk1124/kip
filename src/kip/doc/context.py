"""Per-build state: the document's folder and its own Python modules.

Everything a build needs to know about "where am I" lives in a
:class:`BuildContext` held in a context variable, not in module globals or
``sys.path``. Two documents can therefore build in the same process -- in
threads, a server, or a test run over many projects -- without reading each
other's ``input/`` files or each other's ``analysis.py``.
"""

from __future__ import annotations

import builtins
import importlib.util
import itertools
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

__all__ = ["BuildContext", "current", "document_dir", "project_path", "building"]

_CURRENT: ContextVar["BuildContext | None"] = ContextVar("kip_build", default=None)
_SERIAL = itertools.count(1)


@dataclass
class BuildContext:
    """Where the document lives, and the local modules it has imported."""

    root: Path | None
    modules: dict[str, ModuleType] = field(default_factory=dict)
    serial: int = field(default_factory=lambda: next(_SERIAL))

    def local_module(self, name: str) -> ModuleType | None:
        """``analysis`` for ``import analysis`` beside doc.py, loaded fresh for this build."""
        if self.root is None or "." in name:
            return None
        if name in self.modules:
            return self.modules[name]
        path = self.root / f"{name}.py"
        if not path.is_file() or path.name == "doc.py":
            return None
        # A unique name keeps concurrent builds apart; it is registered only
        # while this build runs, because dataclasses and pickling look a
        # class's module up there.
        qualified = f"_kip_build_{self.serial}.{name}"
        spec = importlib.util.spec_from_file_location(qualified, path)
        module = importlib.util.module_from_spec(spec)
        module.__dict__["__builtins__"] = self.builtins()
        self.modules[name] = module
        sys.modules[qualified] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del self.modules[name]
            sys.modules.pop(qualified, None)
            raise
        return module

    def builtins(self) -> dict:
        """Builtins whose ``import`` finds this document's own modules first."""
        real_import = builtins.__import__

        def kip_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level == 0:
                module = self.local_module(name)
                if module is not None:
                    return module
            return real_import(name, globals, locals, fromlist, level)

        return {**builtins.__dict__, "__import__": kip_import}

    def close(self) -> None:
        for name in list(sys.modules):
            if name.startswith(f"_kip_build_{self.serial}."):
                del sys.modules[name]


def current() -> BuildContext | None:
    return _CURRENT.get()


def document_dir() -> Path | None:
    ctx = _CURRENT.get()
    return ctx.root if ctx is not None else None


def project_path(path) -> Path:
    """A path relative to the document being built (or the working directory)."""
    p = Path(path)
    if p.is_absolute():
        return p
    return (document_dir() or Path.cwd()) / p


@contextmanager
def building(root: Path | str | None):
    """Make ``root`` the current document folder for the duration of a build."""
    ctx = BuildContext(Path(root).resolve() if root is not None else None)
    token = _CURRENT.set(ctx)
    try:
        yield ctx
    finally:
        _CURRENT.reset(token)
        ctx.close()
