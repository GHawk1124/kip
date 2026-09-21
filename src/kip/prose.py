"""Python text cells and the literal regions inside their Typst markup."""
from __future__ import annotations

import ast
import re


CITE_RE = re.compile(r"@(?P<kind>val|blk|req|src):(?P<target>[A-Za-z_][A-Za-z0-9_\-]*)")
_STRING_START = re.compile(r"(?i)^(?:r|u|f|fr|rf|b|br|rb)?['\"]")


def text_expression(source: str):
    """Recognize Python strings; leave legacy unquoted prose supported."""
    source = source.strip()
    if not source:
        return ast.Expression(ast.Constant(""))
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError:
        if _STRING_START.match(source):
            raise
        return None
    if isinstance(tree.body, ast.JoinedStr):
        return tree
    if isinstance(tree.body, ast.Constant) and isinstance(tree.body.value, str):
        return tree
    if _STRING_START.match(source):
        raise ValueError("a text cell needs a Python string, not bytes")
    return None


def text_template(source: str) -> tuple[str, ast.Expression | None]:
    """Decode static prose for citation analysis without evaluating expressions."""
    tree = text_expression(source)
    if tree is None:
        return source, None
    if isinstance(tree.body, ast.Constant):
        return tree.body.value, tree
    # A placeholder separates literals, so references cannot accidentally span
    # a Python interpolation. The expression's names are analysed separately.
    return "".join(v.value if isinstance(v, ast.Constant) else "\0"
                   for v in tree.body.values), tree


def read_text(source: str, namespace: dict) -> str:
    tree = text_expression(source)
    return source.strip() if tree is None else eval(compile(ast.fix_missing_locations(tree), "<text>", "eval"), namespace)


def quote(value) -> str:
    """A Typst string literal; also handles newlines and control characters."""
    escapes = {'"': '\\"', '\\': '\\\\', '\n': '\\n', '\r': '\\r', '\t': '\\t'}
    return '"' + "".join(escapes.get(c, "\\u{" + format(ord(c), "x") + "}"
                                    if ord(c) < 32 or ord(c) == 127 else c)
                          for c in str(value)) + '"'


def literal(value) -> str:
    return f"#text({quote(value)})"


def regions(text: str):
    """Yield (start, end, literal) spans, retaining every original character.

    Backtick code, escaped characters, comments and native code strings are
    opaque. Content arguments inside native calls remain ordinary markup.
    This is a lexical boundary, not an alternative Typst parser.
    """
    i = start = 0
    stack = []  # closing delimiter and language of a nested expression/content
    mode = "markup"
    implicit = False
    statement = False
    while i < len(text):
        end = None
        c = text[i]
        if c == "\\":
            end = min(len(text), i + 2)
        elif c == "`":
            fence = re.match(r"`+", text[i:])[0]
            match = re.search(r"(?<!`)" + re.escape(fence) + r"(?!`)", text[i + len(fence):])
            end = len(text) if match is None else i + len(fence) + match.end()
        elif text.startswith("/*", i):
            depth, end = 1, i + 2
            while end < len(text) and depth:
                if text.startswith("/*", end):
                    depth += 1
                    end += 2
                elif text.startswith("*/", end):
                    depth -= 1
                    end += 2
                else:
                    end += 1
        elif text.startswith("//", i) and (i == 0 or text[i - 1] not in ":/"):
            end = text.find("\n", i)
            if end < 0:
                end = len(text)
        elif c == '"' and mode in ("code", "math"):
            end = i + 1
            while end < len(text):
                if text[end] == "\\":
                    end += 2
                elif text[end] == '"':
                    end += 1
                    break
                else:
                    end += 1
            end = min(end, len(text))
        if end is not None:
            if start < i:
                yield start, i, False
            yield i, end, True
            start = i = end
            continue
        if c == "#" and i + 1 < len(text) and not text[i + 1].isspace() and text[i + 1] != "#":
            mode, implicit = "code", True
            word = re.match(r"#([\w-]+)", text[i:])
            statement = bool(word and word[1] in ("let", "set", "show", "if", "for", "while", "import", "include", "context"))
        elif c == "$" and mode != "code":
            mode = "markup" if mode == "math" else "math"
        elif c in "({" and mode == "code":
            stack.append((")" if c == "(" else "}", mode))
        elif c == "[":
            stack.append(("]", mode))
            mode = "markup"
        elif stack and c == stack[-1][0]:
            _, mode = stack.pop()
            if not stack and implicit and not statement:
                mode, implicit = "markup", False
        elif c == "\n" and not stack and mode != "math":
            mode, implicit = "markup", False
        elif c.isspace() and not stack and implicit and not statement:
            mode, implicit = "markup", False
        i += 1
    if start < len(text):
        yield start, len(text), False


def transform(text: str, fn) -> str:
    parts = []
    for start, end, protected in regions(text):
        part = text[start:end]
        if protected:
            parts.append(part)
        elif start and text[start - 1] != "\n":
            # Do not create a new line-start at a lexical boundary.
            parts.append(fn("\0" + part)[1:])
        else:
            parts.append(fn(part))
    return "".join(parts)


def citations(text: str):
    return tuple((m["kind"], m["target"])
                 for start, end, protected in regions(text) if not protected
                 for m in CITE_RE.finditer(text[start:end]))


def headings(text: str) -> str:
    return transform(text, lambda part: re.sub(
        r"^(\s*)(#{1,6})[ \t]+(\S.*)$",
        lambda m: m[1] + "=" * len(m[2]) + " " + m[3], part, flags=re.MULTILINE))
