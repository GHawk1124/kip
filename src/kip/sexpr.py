"""S-expressions, as KiCad writes its schematics, boards, symbols and netlists."""
from __future__ import annotations

import re

__all__ = ["parse", "Node"]

_TOKEN = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))', re.S)
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"'}


class Node(list):
    """``(name child child ...)``: a list whose first item is its name."""

    @property
    def name(self) -> str:
        return self[0] if self and isinstance(self[0], str) else ""

    @property
    def args(self) -> list:
        return self[1:]

    def find(self, name: str) -> "Node | None":
        return next((c for c in self[1:] if isinstance(c, Node) and c.name == name), None)

    def findall(self, name: str) -> list["Node"]:
        return [c for c in self[1:] if isinstance(c, Node) and c.name == name]

    def children(self) -> list["Node"]:
        return [c for c in self[1:] if isinstance(c, Node)]

    def value(self, name: str, default=None, index: int = 1):
        """The first argument of child ``name``: ``(width 0.25)`` -> 0.25."""
        child = self.find(name)
        if child is None or len(child) <= index:
            return default
        return child[index]

    def number(self, name: str, default: float = 0.0, index: int = 1) -> float:
        value = self.value(name, None, index)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def xy(self, name: str = "at") -> tuple[float, float, float]:
        """``(at x y angle)`` as numbers, the angle 0 when absent."""
        child = self.find(name)
        if child is None:
            return 0.0, 0.0, 0.0
        nums = [float(v) for v in child[1:4] if _is_number(v)]
        nums += [0.0] * (3 - len(nums))
        return nums[0], nums[1], nums[2]

    def flag(self, name: str) -> bool:
        """``(hide yes)``, ``(hide)`` or a bare ``hide`` among the arguments."""
        child = self.find(name)
        if child is not None:
            return len(child) == 1 or child[1] in ("yes", "true")
        return name in [c for c in self[1:] if isinstance(c, str)]


def _is_number(value) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _unescape(text: str) -> str:
    if "\\" not in text:
        return text
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(1)), text)


def parse(text: str) -> Node:
    """The first S-expression in ``text``."""
    stack: list[Node] = [Node()]
    for m in _TOKEN.finditer(text):
        if m.group(1):
            child = Node()
            stack[-1].append(child)
            stack.append(child)
        elif m.group(2):
            if len(stack) == 1:
                raise ValueError("unbalanced ')' in S-expression")
            stack.pop()
            if len(stack) == 1:
                break
        elif m.group(3) is not None:
            stack[-1].append(_unescape(m.group(3)))
        elif m.group(4) is not None:
            stack[-1].append(m.group(4))
    if len(stack) != 1 or not stack[0]:
        raise ValueError("incomplete S-expression: a '(' is never closed")
    return stack[0][0]
