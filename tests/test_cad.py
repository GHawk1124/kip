"""Optional CAD integration: real projection, planar exports and vector PDF."""
import importlib.util

import pytest

pytestmark = pytest.mark.skipif(importlib.util.find_spec("build123d") is None,
                                reason="requires kip[cad]")


@pytest.fixture(scope="module")
def model():
    from kip.cad import load_build123d
    bd = load_build123d()
    return bd, bd.Box(80, 50, 10) - bd.Cylinder(8, 10)


@pytest.mark.parametrize("view", ["iso", "top", "side", "bottom"])
def test_solid_views_are_vector_svg(model, view):
    from kip.cad import cad_view
    from kip.doc import build
    from kip.render import emit
    from kip.render.pdf import compile_pdf
    import pymupdf
    bd, part = model
    drawing = cad_view(part, view)
    assert b"<svg" in drawing.svg
    doc = build(source='from kip import Drawing\n# %% kip.draw id=v\nv = Drawing(body="circle((0,0), radius: 1)")', path="doc.py")
    doc.results["v"].content = drawing
    files = emit(doc)
    assert files["drawings/v.svg"] == drawing.svg
    pdf = pymupdf.open(stream=compile_pdf(files))
    assert not pdf[0].get_images()
    assert len(pdf[0].get_drawings()) > 4


def test_sections_and_faces_export_true_size_xy_geometry(model, tmp_path):
    from kip.cad import cad_section, cad_face
    import ezdxf
    from ezdxf import bbox
    bd, part = model
    # Non-XY section exercises flattening, not just copying already-flat edges.
    section = cad_section(part, bd.Plane.XZ, dxf="section.dxf")
    face = cad_face(part.faces().filter_by(bd.Axis.Z).sort_by(bd.Axis.Z)[-1], dxf="face.dxf")
    for drawing, expected in [(section, (80, 10)), (face, (80, 50))]:
        name, data = next(iter(drawing.attachments.items()))
        target = tmp_path / name
        target.write_bytes(data)
        doc = ezdxf.readfile(target)
        assert doc.units == 4  # millimetres
        assert not doc.audit().errors
        ext = bbox.extents(doc.modelspace())
        assert ext.size.x == pytest.approx(expected[0])
        assert ext.size.y == pytest.approx(expected[1])
        assert ext.size.z == pytest.approx(0)
    assert len(ezdxf.readfile(tmp_path / "face.dxf").modelspace().query("CIRCLE")) == 1


def test_section_must_intersect(model):
    from kip.cad import cad_section
    bd, part = model
    with pytest.raises(ValueError, match="intersect"):
        cad_section(part, bd.Plane.XY.offset(100), dxf="empty.dxf")
