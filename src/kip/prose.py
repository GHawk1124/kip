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
    for start, end, tag in _lex(text):
        yield start, end, tag is not None


#: References kip resolves itself; any other ``@name`` is Typst's.
_KIP_REF = re.compile(r"@(?:val|blk|req|src):")
_LABEL = re.compile(r"<([A-Za-z_][\w\-.:]*)>")
_REF = re.compile(r"@([A-Za-z_][\w\-.:]*)")


def _closing_dollar(text: str, i: int) -> int:
    j = text.find("$", i + 1)
    while j > 0 and text[j - 1] == "\\":
        j = text.find("$", j + 1)
    return j


def _literal_char(text: str, i: int) -> bool:
    """Whether a markup character prints as itself rather than as Typst syntax.

    Prose is written by people and agents who mean "bolt #4", "<0.5 mm",
    "j.smith@acme.com", "$45", "~5 mm" and "8 * 2" literally. Typst would read
    each as code, a label, a reference, math, a non-breaking space or bold,
    and either fail the build or drop the characters without a word. Only a
    character that cannot be the markup the author meant is escaped:
    ``#strong[...]``, ``$x$``, ``@val:name``, ``Fig.~3``, ``*bold*`` and a
    referenced ``<label>`` are kept.
    """
    c, nxt = text[i], text[i + 1:i + 2]
    if c == "\\":  # a backslash before a letter escapes nothing: C:\temp
        return nxt.isalnum() and not text.startswith("u{", i + 1)
    if c == "#":
        if nxt and (nxt.isalpha() or nxt in '_([{"'):
            return False
        line = text.rfind("\n", 0, i) + 1
        heading = re.match(r"[ \t]*(#{1,6})[ \t]", text[line:])
        return not (heading and line + heading.start(1) <= i < line + heading.end(1))
    if c == "$":  # an amount of money, not the start of math
        if not nxt.isdigit():
            return False
        j = _closing_dollar(text, i)
        if j < 0:
            return True
        inner = text[i + 1:j]
        return text[j + 1:j + 2].isdigit() or inner != inner.rstrip() or "\n\n" in inner
    if c == "<":
        label = _LABEL.match(text, i)
        if label:
            return re.search(rf"@{re.escape(label[1])}(?![\w\-:])", text) is None
        return bool(nxt) and (nxt.isalnum() or nxt in "_-.:")
    if c == "@":
        if _KIP_REF.match(text, i):
            return False
        if i and (text[i - 1].isalnum() or text[i - 1] in "._-"):
            return True  # an email address
        ref = _REF.match(text, i)
        return bool(ref) and f"<{ref[1].rstrip('.:')}>" not in text
    if c == "~":  # "~5 mm" is approximately, "Fig.~3" a non-breaking space
        return nxt.isdigit() and (i == 0 or text[i - 1].isspace() or text[i - 1] in "([")
    if c in "*_":  # "8 * 2" multiplies; *strong* and _emph_ touch their words
        start, end = i, i + 1
        while start and text[start - 1] == c:
            start -= 1
        while text[end:end + 1] == c:
            end += 1
        if not ((start == 0 or text[start - 1].isspace())
                and (end == len(text) or text[end].isspace())):
            return False
        line = text.rfind("\n", 0, i) + 1
        return c == "_" or bool(text[line:i].strip())  # "* item" is a bullet
    return False


def escape_literals(text: str) -> str:
    """Escape the markup characters :func:`_literal_char` reads as text."""
    return "".join("\\" + text[s:e] if tag == "literal" else text[s:e]
                   for s, e, tag in _lex(text, _literal_char))


def _lex(text: str, literal=None):
    """Yield ``(start, end, tag)``: ``None`` for markup, code and math;
    ``"protected"`` for opaque spans; ``"literal"`` for a markup character
    ``literal(text, i)`` says must print as itself."""
    i = start = 0
    stack = []  # closing delimiter and language of a nested expression/content
    mode = "markup"
    implicit = False
    statement = False
    while i < len(text):
        end = None
        c = text[i]
        if literal is not None and mode == "markup" and c in "\\#$<@~*_" and literal(text, i):
            if start < i:
                yield start, i, None
            yield i, i + 1, "literal"
            start = i = i + 1
            continue
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
                yield start, i, None
            yield i, end, "protected"
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
        yield start, len(text), None


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
    """Markdown habits in Typst: ``# Heading``, ``* item`` and ``**bold**``.

    Typst reads ``**bold**`` as two empty strong runs and prints the word
    plain, so the doubled marks become single ones.
    """
    def convert(part: str) -> str:
        part = re.sub(r"^(\s*)(#{1,6})[ \t]+(\S.*)$",
                      lambda m: m[1] + "=" * len(m[2]) + " " + m[3], part, flags=re.MULTILINE)
        part = re.sub(r"^([ \t]*)\*[ \t]+(?=\S)", r"\1- ", part, flags=re.MULTILINE)
        return re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"*\1*", part)
    return transform(text, convert)
