"""Map compiler diagnostics to authored cells without changing Typst scope."""
from __future__ import annotations

import json
import re

from ..prose import text_template


class RenderError(ValueError):
    """A compiler error with the document location and original diagnostic."""

    def __init__(self, error, project):
        self.diagnostic = getattr(error, "diagnostic", str(error))
        self.locations = []
        for match in re.finditer(r"(?:/|\\)?main\.typ:(\d+):(\d+)", self.diagnostic):
            location = getattr(project, "locations", {}).get(int(match[1]))
            if location and location not in self.locations:
                self.locations.append(location)
        message = getattr(error, "message", str(error))
        if self.locations:
            path, block, line = self.locations[0]
            message = f"{path}:{line}: [{block}] Typst: {message}"
        else:
            message = "Typst: " + message
        hints = getattr(error, "hints", ())
        super().__init__(message + "".join(f"\n  hint: {hint}" for hint in hints)
                         + "\n" + self.diagnostic)


def mark(block, markup, *, prose=False):
    line, advance = block.body_start, False
    if prose and block.source.strip():
        template, tree = text_template(block.source)
        if tree is None:
            advance = True
        elif (tree.body.end_lineno - tree.body.lineno == template.count("\n")
              and markup.count("\n") == template.count("\n")):
            line += block.source[:len(block.source) - len(block.source.lstrip())].count("\n")
            advance = True
    data = json.dumps([block.id, line, advance])
    return f"// kip-source: {data}\n{markup}\n// kip-source-end\n"


class TypstProject(dict):
    def __init__(self, files, path):
        super().__init__(files)
        self.locations = {}
        stack = []
        for number, line in enumerate(files["main.typ"].decode().splitlines(), 1):
            if line.startswith("// kip-source: "):
                block, original, advance = json.loads(line.removeprefix("// kip-source: "))
                stack.append((block, original, advance, number + 1))
            elif line == "// kip-source-end":
                if stack:
                    stack.pop()
            elif stack:
                block, original, advance, start = stack[-1]
                self.locations[number] = (str(path), block, original + (number - start if advance else 0))
