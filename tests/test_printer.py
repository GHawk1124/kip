import pytest
import sympy as sp
import typst

from kip.math.printer import typst_math

x, y, n = sp.symbols("x y n")
M, c, I, A = sp.symbols("M c I A", positive=True)
sigma_max = sp.Symbol("sigma_max")


@pytest.mark.parametrize("expr,expected", [
    (M * c / I,                    "frac(M dot c, I)"),
    (x ** 2,                       "x^2"),
    (x ** -2,                      "frac(1, x^2)"),
    (sp.sqrt(x),                   "sqrt(x)"),
    (sp.root(x, 3),                "root(3, x)"),
    (sp.Rational(3, 4),            "frac(3, 4)"),
    (sigma_max,                    'sigma_"max"'),
    (sp.Symbol("F_y"),             "F_y"),
    (sp.Eq(sigma_max, M * c / I),  'sigma_"max" = frac(M dot c, I)'),
    (sp.Le(x, y),                  "x <= y"),
    (sp.sin(x) ,                   "sin(x)"),
    (sp.log(x),                    "ln(x)"),
    (sp.exp(x),                    "e^x"),
    (sp.Derivative(y, x),          "frac(dif y, dif x)"),
    (sp.Integral(x ** 2, (x, 0, 1)), "integral_0^1 x^2 thin dif x"),
    (sp.Sum(x ** n, (n, 1, 10)),   "sum_(n=1)^(10) x^n"),
    (sp.Matrix([[1, 2], [3, 4]]),  "mat(1, 2; 3, 4)"),
    (sp.Function("MS")(x),         'op("MS")(x)'),
    (sp.pi,                        "pi"),
])
def test_golden_markup(expr, expected):
    assert typst_math(expr) == expected


def test_greek_names_are_not_quoted():
    assert typst_math(sp.Symbol("sigma")) == "sigma"
    assert typst_math(sp.Symbol("theta")) == "theta"


def test_multiletter_subscript_is_quoted_as_text():
    """Bare 'max' in Typst math would be a symbol lookup, not the word."""
    assert typst_math(sp.Symbol("sigma_allow")) == 'sigma_"allow"'


def test_piecewise():
    z = sp.Symbol("z")
    out = typst_math(sp.Piecewise((z, z > 0), (-z, True)))
    assert out.startswith("cases(") and '"otherwise"' in out


def test_exp_of_fraction_uses_operator_form():
    """A fraction in a superscript renders microscopically."""
    L = sp.Symbol("L")
    assert typst_math(sp.exp(-x / L)).startswith("exp(")


EXPRESSIONS = [
    M * c / I, x ** 2, sp.sqrt(x), sp.Rational(3, 4), sigma_max,
    sp.Eq(sigma_max, M * c / I), sp.sin(x) + sp.cos(x) ** 2,
    sp.Derivative(y, x), sp.Integral(x ** 2, (x, 0, 1)),
    sp.Sum(x ** n, (n, 1, 10)), sp.Matrix([[1, 2], [3, 4]]),
    sp.Piecewise((x, x > 0), (-x, True)), sp.Float(2.07e11),
    sp.Limit(sp.sin(x) / x, x, 0), sp.log(x, 10), sp.Abs(x),
]


@pytest.mark.parametrize("expr", EXPRESSIONS, ids=lambda e: str(e)[:24])
def test_output_is_valid_typst(expr):
    """Golden strings are worthless if Typst cannot compile them."""
    src = f"#set page(width: 200mm, height: auto)\n$ {typst_math(expr)} $"
    typst.compile({"main.typ": src.encode()}, timestamp=0)
