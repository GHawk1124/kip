"""Dimensioned explanatory vector views derived from the shared CAD profile."""
import base64
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon,Rectangle,Circle
from design import *

def finish(fig,name):
    fig.savefig(ASSETS/f'{name}.svg',bbox_inches='tight',transparent=True)
    fig.savefig(ASSETS/f'{name}.png',bbox_inches='tight',transparent=True,dpi=180)
    plt.close(fig)

def dim(ax,a,b,label,offset=(0,0),color='#235c78'):
    aa=np.array(a)+offset;bb=np.array(b)+offset
    ax.plot([a[0],aa[0]],[a[1],aa[1]],color=color,lw=.5)
    ax.plot([b[0],bb[0]],[b[1],bb[1]],color=color,lw=.5)
    ax.annotate('',xy=aa,xytext=bb,arrowprops=dict(arrowstyle='<->',color=color,lw=.7))
    mid=(aa+bb)/2
    ax.text(*mid,label,ha='center',va='bottom',fontsize=8,color=color,
            bbox=dict(facecolor='white',edgecolor='none',pad=1))

def main():
    plt.rcParams.update({'font.size':9,'svg.fonttype':'none','text.color':'#243b50'})
    # Arrange actual CAD projections and the actual center-plane section in one
    # vector sheet. Nesting SVGs preserves the original CAD paths without tracing.
    import xml.etree.ElementTree as ET
    ns='http://www.w3.org/2000/svg'
    ET.register_namespace('',ns)
    sheet=ET.Element(f'{{{ns}}}svg',{'width':'800','height':'780','viewBox':'0 0 800 780'})
    views=[('front.svg','FRONT / OUTSIDE',0,0,'116 mm overall; 82 mm outside diameter'),
           ('section_cad.svg','SECTION A-A / THROUGH THE CENTER',400,0,'XZ plane, y = 0; actual CAD intersection'),
           ('end.svg','END / LOOKING INTO THE TUBE',0,390,'58 mm active face; 70 mm frame'),
           ('housing_iso.svg','ONE HOUSING HALF / USE TWICE',400,390,'Opposing half is the same part, reversed')]
    for name,title,x,y,caption in views:
        label=ET.SubElement(sheet,f'{{{ns}}}text',{'x':str(x+200),'y':str(y+22),
            'text-anchor':'middle','font-family':'Arial','font-size':'13','fill':'#243b50'})
        label.text=title
        nested=ET.fromstring((ASSETS/name).read_bytes())
        nested.set('x',str(x+45));nested.set('y',str(y+40))
        nested.set('width','310');nested.set('height','290')
        nested.set('preserveAspectRatio','xMidYMid meet')
        for element in nested.iter():
            if 'id' in element.attrib: element.set('id',name.replace('.','_')+'_'+element.attrib['id'])
        sheet.append(nested)
        label=ET.SubElement(sheet,f'{{{ns}}}text',{'x':str(x+200),'y':str(y+358),
            'text-anchor':'middle','font-family':'Arial','font-size':'12','fill':'#243b50'})
        label.text=caption
    (ASSETS/'orthographic_sheet.svg').write_bytes(ET.tostring(sheet,encoding='utf-8',xml_declaration=True))
    # Axial section uses r->y, z->x, preserving geometry exactly.
    fig,ax=plt.subplots(figsize=(9,5.7))
    for sx in [-1,1]:
        for sy in [-1,1]:
            pts=np.array([[sx*z,sy*r] for r,z in PROFILE])
            ax.add_patch(Polygon(pts,facecolor='#c7d6df',edgecolor='#334c60',lw=.8))
    for x,w,col in [(-.57,.48,'#6aa7b0'),(-.09,.18,'#285e79'),(.09,.48,'#6aa7b0')]:
        ax.add_patch(Rectangle((x,-35),w,70,color=col))
    for sign in [-1,1]:
        for y in [-35,29]:
            ax.add_patch(Rectangle((.57 if sign>0 else -.74,y),.17,6,color='#dca55b'))
    ax.plot([-66,66],[0,0],ls='-.',color='#98a9b0',lw=.6)
    dim(ax,(-58,-9.525),(58,-9.525),'116 overall',(0,-40))
    dim(ax,(0,-41),(0,41),'Ø82',(-64,0))
    dim(ax,(38,9.525),(58,9.525),'20 straight weld stub',(0,11))
    ax.annotate('Ø19.05 OD / Ø15.75 bore\n0.750 × 0.065 in tube interface',xy=(53,8),xytext=(22,34),arrowprops=dict(arrowstyle='->',lw=.7))
    ax.annotate('Housing-to-housing orbital weld\nØ82 seam; 2.50 radial wall',xy=(0,40.5),xytext=(-54,52),arrowprops=dict(arrowstyle='->',lw=.7))
    ax.annotate('Detail B: crush land / frame / moat',xy=(0,32),xytext=(10,47),arrowprops=dict(arrowstyle='->',lw=.7))
    ax.annotate('Ø58 active disc\n3 contacting mesh layers',xy=(0,15),xytext=(-52,23),arrowprops=dict(arrowstyle='->',lw=.7))
    ax.annotate('Flow',xy=(47,0),xytext=(23,0),va='center',arrowprops=dict(arrowstyle='->',color='#235c78',lw=1.5))
    ax.set_aspect('equal');ax.set_xlim(-72,70);ax.set_ylim(-56,62);ax.axis('off')
    finish(fig,'dimensioned_section')
    # Detail B - axial scale enlarged to resolve sub-mm functional geometry.
    fig,ax=plt.subplots(figsize=(9,4.4))
    pp=np.array(PROFILE)
    for sign in [-1,1]:
        ax.add_patch(Polygon(np.column_stack([pp[:,0],sign*pp[:,1]]),facecolor='#c7d6df',edgecolor='#334c60',lw=1))
    for z,t,col in [(-.57,.48,'#6aa7b0'),(-.09,.18,'#285e79'),(.09,.48,'#6aa7b0')]:
        ax.add_patch(Rectangle((28,z),7,t,color=col))
    for z in [-.74,.57]:ax.add_patch(Rectangle((29,z),6,.17,facecolor='#dca55b',edgecolor='#b17e33',lw=.5))
    ax.add_patch(Rectangle((33,-.74),1,.148*10,facecolor='none',edgecolor='#9b453e',hatch='////',lw=1))
    ax.annotate('Coined 316L sheet\nland width 0.40',xy=(32,.71),xytext=(28.1,2.8),arrowprops=dict(arrowstyle='->',lw=.7))
    ax.annotate('Closed resistance seam\nr33.0–34.0; through all 5 layers',xy=(33.5,.1),xytext=(28.1,-3),arrowprops=dict(arrowstyle='->',lw=.7))
    ax.annotate('Thermal moat\nr35.2–37; depth 2',xy=(36,1.6),xytext=(34.2,3.1),arrowprops=dict(arrowstyle='->',lw=.7))
    ax.annotate('Independent stop\nr37–38; datum A',xy=(37.5,0),xytext=(37,-3),arrowprops=dict(arrowstyle='->',lw=.7))
    ax.annotate('Fusion rim\nr38.5–41',xy=(40,.05),xytext=(39,2.8),arrowprops=dict(arrowstyle='->',lw=.7))
    dim(ax,(31.8,-.74),(31.8,.74),'1.480 land gap',(-1.1,0))
    ax.set(xlim=(28,42),ylim=(-3.6,3.8),xlabel='Radius from axis (mm)',ylabel='Axial position z (mm)')
    ax.spines[['top','right']].set_visible(False)
    ax.set_title('Detail B / radial and axial scales differ; dimensions govern',loc='left')
    finish(fig,'seal_detail')
    # Flat element construction and face annuli.
    fig,(ax,bx)=plt.subplots(1,2,figsize=(9,4.2))
    for radius,color in [(35,'#dca55b'),(29,'#7aaeb4')]:ax.add_patch(Circle((0,0),radius,facecolor=color,edgecolor='#334c60',lw=.8))
    for radius,ls,col in [(32,'--','#235c78'),(33,'-','#9b453e'),(34,'-','#9b453e')]:ax.add_patch(Circle((0,0),radius,fill=False,ls=ls,color=col,lw=1))
    # Illustrative coarse weave, clipped to active circle; not exact Dutch cloth.
    circle=Circle((0,0),29,transform=ax.transData)
    for v in np.arange(-29,30,2):
        for x,y in [([-29,29],[v,v]),([v,v],[-29,29])]:
            line,=ax.plot(x,y,color='#376f7c',lw=.35);line.set_clip_path(circle)
    ax.text(0,-42,'Ø70 trimmed OD / Ø58 opening\nDashed: Ø64 seal track\nRed: Ø66–68 closed weld annulus',ha='center',va='top')
    ax.set(xlim=(-42,42),ylim=(-57,40));ax.set_aspect('equal');ax.axis('off')
    layers=[('Frame / annealed 316L',.20,'#dca55b'),('Coarse / 40 × 40',.48,'#6aa7b0'),('Fine / candidate 5-S',.18,'#285e79'),('Coarse / 40 × 40',.48,'#6aa7b0'),('Frame / annealed 316L',.20,'#dca55b')]
    y=4.3
    for name,t,col in layers:
        bx.add_patch(Rectangle((0,y),3,t,facecolor=col,edgecolor='#334c60',lw=.5))
        bx.text(3.2,y+t/2,f'{name}\n{t:.3f} mm',va='center',fontsize=8)
        y-=.9
    bx.text(0,-.2,'Exploded spacing is illustrative.\nFinished perimeter T = 1.540 ± 0.006 mm.\nNo spacer between any mesh layers.',fontsize=9)
    bx.set(xlim=(-.1,7.2),ylim=(-1,5.2));bx.axis('off')
    finish(fig,'element_detail')
    # Wrap transparent VTK renders in SVG for Kip's supported drawing transport.
    from PIL import Image
    for name in ['hero','exploded_render','cutaway','pressure_render']:
        path=ASSETS/f'{name}.png';im=Image.open(path)
        data=base64.b64encode(path.read_bytes()).decode()
        (ASSETS/f'{name}_embed.svg').write_text(f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{im.width}" height="{im.height}" viewBox="0 0 {im.width} {im.height}"><image width="{im.width}" height="{im.height}" xlink:href="data:image/png;base64,{data}"/></svg>')

if __name__=='__main__':main()
