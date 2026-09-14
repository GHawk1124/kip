"""Compose CAD-generated views only; no custom plotting of section geometry."""
import base64
import xml.etree.ElementTree as ET
from PIL import Image
from design import ASSETS, C
NS='http://www.w3.org/2000/svg'
ET.register_namespace('',NS)
def compose(name,items,width,height):
    root=ET.Element('{'+NS+'}svg',dict(width=str(width),height=str(height),viewBox=f'0 0 {width} {height}'))
    for filename,title,x,y,w,h in items:
        label=ET.SubElement(root,'{'+NS+'}text',{'x':str(x+w/2),'y':str(y+16),'text-anchor':'middle','font-family':'Arial','font-size':'12','fill':'#243b50'});label.text=title
        child=ET.fromstring((ASSETS/filename).read_bytes())
        child.set('x',str(x));child.set('y',str(y+24));child.set('width',str(w));child.set('height',str(h-24));child.set('preserveAspectRatio','xMidYMid meet')
        root.append(child)
    (ASSETS/name).write_bytes(ET.tostring(root,encoding='utf-8',xml_declaration=True))
def main():
    for name in ['hero','exploded_render','cutaway']:
        path=ASSETS/f'{name}.png'; im=Image.open(path);box=im.getbbox();im=im.crop(box);im.save(path)
        data=base64.b64encode(path.read_bytes()).decode()
        (ASSETS/f'{name}_embed.svg').write_text(f'<svg xmlns="{NS}" xmlns:xlink="http://www.w3.org/1999/xlink" width="{im.width}" height="{im.height}" viewBox="0 0 {im.width} {im.height}"><image width="{im.width}" height="{im.height}" xlink:href="data:image/png;base64,{data}"/></svg>')
    compose('cover_pair.svg',[('hero_embed.svg','ASSEMBLED ISOMETRIC',0,0,400,330),('cutaway_embed.svg','HOUSING AND PACK / CUTAWAY ISO',400,0,400,330)],800,330)
    compose('drawing_sheet.svg',[('front.svg','FRONT',0,0,400,370),('section_cad.svg','SECTION A-A / CENTER PLANE',400,0,400,370),('end.svg','END',0,370,400,370),('housing_iso.svg','ONE HOUSING HALF / USE TWICE',400,370,400,370)],800,740)
if __name__=='__main__':main()
