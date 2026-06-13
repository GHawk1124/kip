"""Document model: parse, analyse, validate and execute kip documents."""

from .blocks import Block, CODE_KINDS, HANDCALC_KINDS, KINDS
from .graph import CycleError, DependencyGraph, analyze
from .kernel import BlockResult, Document, ExecutionError, build, execute
from .loader import KipSyntaxError, load, parse, replace_body
from .validate import Diagnostic, ValidationError, validate_all

__all__ = [
    "Block", "KINDS", "CODE_KINDS", "HANDCALC_KINDS",
    "parse", "load", "replace_body", "KipSyntaxError",
    "analyze", "DependencyGraph", "CycleError",
    "validate_all", "Diagnostic", "ValidationError",
    "build", "execute", "Document", "BlockResult", "ExecutionError",
]
