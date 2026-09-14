"""Run with ParaView's pvpython from this project directory.
Produces a true ParaView transparent render of the provided analysis field.
The delivered companion PNG is rendered with PyVista/VTK when pvpython is absent.
"""
from pathlib import Path
from paraview.simple import *
root=Path(__file__).resolve().parent
model=XMLUnstructuredGridReader(FileName=[str(root/'output/analysis/housing_pressure_650psi.vtu')])
view=GetActiveViewOrCreate('RenderView')
display=Show(model,view)
ColorBy(display,('CELLS','von_Mises_MPa'))
display.SetScalarBarVisibility(view,True)
GetColorTransferFunction('von_Mises_MPa').RescaleTransferFunction(0,110)
view.OrientationAxesVisibility=0
view.CameraPosition=[100,-135,100];view.CameraFocalPoint=[0,0,24]
view.CameraViewUp=[0,0,1];view.CameraParallelProjection=1
view.CameraParallelScale=39
SaveScreenshot(str(root/'assets/paraview_pressure.png'),view,
               ImageResolution=[1800,1500],TransparentBackground=1)
