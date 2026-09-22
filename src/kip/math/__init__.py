"""Math rendering: calc cells and sympy expressions, straight to Typst."""

from .calc import Equation, RenderedCalc, render_calc
from .printer import TypstPrinter, typst_math

__all__ = ["typst_math", "TypstPrinter", "render_calc", "RenderedCalc", "Equation"]
