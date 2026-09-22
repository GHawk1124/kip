"""Document extensions: conventions layered on top of the core kernel.

The kernel runs cells and records their state; it does not know what a
component packet is. A convention such as the packet plugs in by providing an
:class:`Extension`. A factory registered with :func:`register` looks at the
parsed cells and returns an extension when a document opts in (for the packet,
``# %% packet component``).

Hooks, in the order a build calls them:

``cells``        the authored cells, after the extension has planned them
``provided``     names ``load`` will supply, so they resolve before execution
``load(doc)``    namespace additions, re-read on every build
``finish(doc)``  after execution: add generated cells, compute status
``outstanding``  ``{section: (state, reason)}`` that keeps ``kip check`` failing
``page(spec)``   adjust page settings (title, document number) before emitting

An extension that sets ``draft = True`` asks the kernel to record inputs it
declared but could not find as OPEN/BLOCKED instead of failing the build.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Callable

from .blocks import Block

__all__ = ["Extension", "UnavailableInput", "MissingInput", "register", "plan"]


class UnavailableInput(Exception):
    """A declared input is absent; it is not a Python or schema error."""


class MissingInput:
    """Stands in for an input that is not there yet; any use raises UnavailableInput."""

    def __init__(self, reason):
        self.reason = reason

    def __getattr__(self, name):
        raise UnavailableInput(self.reason)

    def __getitem__(self, key):
        raise UnavailableInput(self.reason)


class Extension:
    """Base class with do-nothing hooks; override what the convention needs."""

    draft = False
    provided: frozenset[str] = frozenset()

    def __init__(self, cells: list[Block]):
        self.cells = cells

    def load(self, doc) -> dict:
        return {}

    def finish(self, doc) -> None:
        pass

    @property
    def outstanding(self) -> dict[str, tuple[str, str]]:
        return {}

    def page(self, spec):
        return spec


Factory = Callable[[list[Block], Path], "Extension | None"]
_FACTORIES: list[str | Factory] = ["kip.packet:prepare"]


def register(factory: Factory) -> None:
    """Add a convention; it is offered every parsed document."""
    _FACTORIES.append(factory)


def plan(blocks: list[Block], path: Path) -> tuple[list[Block], list[Extension]]:
    """Offer the cells to each registered convention; return the cells to run."""
    extensions: list[Extension] = []
    for factory in _FACTORIES:
        if isinstance(factory, str):
            module, _, name = factory.partition(":")
            factory = getattr(importlib.import_module(module), name)
        extension = factory(blocks, path)
        if extension is not None:
            extensions.append(extension)
            blocks = list(extension.cells)
    return blocks, extensions
