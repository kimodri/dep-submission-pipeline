"""Render the README architecture image with the repository's bundled fonts.

Requires Pillow. Run from any directory: python scripts/render_architecture.py
"""
from pathlib import Path
import math
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SCALE = 2
im = Image.new('RGB', (1700*SCALE, 1080*SCALE), 'white')
d = ImageDraw.Draw(im)
INK = '#18232D'
MUTED = '#52616E'
BLUE = '#2877AC'
FONT_DIR = ROOT / 'src/dashboard/static/fonts'

def font(size, title=False):
    f = ImageFont.truetype(str(FONT_DIR / ('montserrat-variable.ttf' if title else 'noto-sans-variable.ttf')), size*SCALE)
    if title:
        f.set_variation_by_axes([650])
    return f

def text(x,y,value,size=22,title=False,fill=INK,anchor='mm'):
    d.text((x*SCALE,y*SCALE),value,font=font(size,title),fill=fill,anchor=anchor)

def line(points,fill=INK,width=3):
    d.line([(int(x*SCALE),int(y*SCALE)) for x,y in points],fill=fill,width=width*SCALE,joint='curve')

def rect(box,fill,outline=None,r=14,width=2):
    d.rounded_rectangle(tuple(int(v*SCALE) for v in box),radius=r*SCALE,fill=fill,outline=outline,width=width*SCALE)

def ellipse(box,fill,outline=None,width=2):
    d.ellipse(tuple(int(v*SCALE) for v in box),fill=fill,outline=outline,width=width*SCALE)

def arrow(points,fill=INK,width=4,dashed=False):
    if dashed:
        for (x1,y1),(x2,y2) in zip(points,points[1:]):
            length=math.hypot(x2-x1,y2-y1)
            for i in range(0,int(length),18):
                a,b=i/length,min(i+10,length)/length
                line([(x1+(x2-x1)*a,y1+(y2-y1)*a),(x1+(x2-x1)*b,y1+(y2-y1)*b)],fill,width)
    else:
        line(points,fill,width)
    x,y=points[-1]; px,py=points[-2]
    angle=math.atan2(y-py,x-px)
    vertices=[(x,y),(x-15*math.cos(angle-.48),y-15*math.sin(angle-.48)),(x-15*math.cos(angle+.48),y-15*math.sin(angle+.48))]
    d.polygon([(int(a*SCALE),int(b*SCALE)) for a,b in vertices],fill=fill)

def database(x,y,color):
    d.rectangle(((x-34)*SCALE,(y-23)*SCALE,(x+34)*SCALE,(y+28)*SCALE),fill=color)
    ellipse((x-34,y+14,x+34,y+42),color)
    ellipse((x-34,y-37,x+34,y-9),color)
    d.arc(((x-34)*SCALE,(y-15)*SCALE,(x+34)*SCALE,(y+13)*SCALE),0,180,fill='white',width=2*SCALE)
    d.arc(((x-34)*SCALE,(y+3)*SCALE,(x+34)*SCALE,(y+31)*SCALE),0,180,fill='white',width=2*SCALE)

text(65,60,'DEP Submission Pipeline',42,True,anchor='lm')
text(65,115,'From GitHub submissions to a dimensional warehouse and published analytics',23,fill=MUTED,anchor='lm')

# Warehouse boundary and vertically connected medallion stages.
rect((640,200,1100,855),'#F3F5F6',r=20)
text(870,240,'MotherDuck warehouse',27,True)
text(870,278,'DuckDB engine  /  Medallion architecture',19,fill=MUTED)
for y,title,color,desc,detail in [
    (375,'Bronze','#AE7345','Raw JSON payloads','Extraction and run metadata'),
    (555,'Silver','#75838D','Cleaned submissions','Normalized fields and derived measures'),
    (735,'Gold','#D2A72D','Dimensional warehouse','Snapshot fact + dimensions + reviewer bridge')]:
    rect((665,y-62,1075,y+65),'white',r=12)
    database(715,y-5,color)
    text(775,y-31,title,27,True,anchor='lm')
    text(775,y+6,desc,20,anchor='lm')
    text(870,y+43,detail,16,fill=MUTED)
arrow([(870,445),(870,485)],'#73818B',3)
arrow([(870,625),(870,665)],'#73818B',3)
text(870,825,'Local development: DuckDB file',18,fill=MUTED)

# GitHub Projects source: project board symbol.
rect((80,320,210,410),'#24292F',r=12)
for x in [96,132,168]:
    rect((x,337,x+25,345),'#8B949E',r=3)
    rect((x,353,x+25,372),'#F0F6FC',r=3)
rect((96,379,121,397),'#58A6FF',r=3)
rect((132,379,157,397),'#3FB950',r=3)
text(145,450,'GitHub Projects',25,True)
text(145,485,'Builder submissions',20,fill=MUTED)
text(145,514,'GraphQL API',19,fill=MUTED)
arrow([(230,375),(350,375)])
text(290,345,'Extract',18,fill=MUTED)

# Python-inspired interlocking shapes, with explicit technology label.
rect((390,315,452,368),'#3776AB',r=16)
rect((370,343,425,395),'#3776AB',r=16)
rect((414,372,477,426),'#FFD343',r=16)
rect((442,347,497,397),'#FFD343',r=16)
ellipse((402,326,410,334),'white')
ellipse((458,407,466,415),'white')
text(434,465,'Python pipeline',25,True)
text(434,500,'Requests + pandas',20,fill=MUTED)
arrow([(510,375),(625,375)])
text(566,345,'Load',18,fill=MUTED)

# Orchestration is separate from data flow.
rect((80,650,535,820),'#F2F7FC',r=16)
ellipse((105,680,159,734),BLUE)
line([(132,690),(132,706),(145,714)],'white',3)
text(180,694,'GitHub Actions',25,True,anchor='lm')
text(180,733,'Daily at 08:11 Asia/Manila',20,fill=MUTED,anchor='lm')
text(180,769,'Scheduled or manual runs',18,fill=MUTED,anchor='lm')
arrow([(434,650),(434,540)],BLUE,3,True)
text(470,593,'Runs',18,fill=BLUE,anchor='lm')

# Gold serves SQL, which feeds the dashboard build.
arrow([(1115,735),(1180,735)])
rect((1200,684,1280,752),'#EAF1F7',BLUE,r=10)
text(1240,718,'SQL',25,True,BLUE)
text(1240,797,'Analytics',23,True)
text(1240,829,'Progress + workload',17,fill=MUTED)
arrow([(1300,735),(1390,735)])
rect((1420,675,1550,760),'white','#364552',r=8)
line([(1420,695),(1550,695)],'#364552',2)
for x,col in [(1430,'#AE7345'),(1442,'#75838D'),(1454,'#D2A72D')]:
    ellipse((x,682,x+5,687),col)
for x,height,col in [(1437,23,BLUE),(1462,37,'#42A59B'),(1487,47,'#D2A72D'),(1512,31,BLUE)]:
    rect((x,750-height,x+14,750),col,r=2)
text(1485,797,'Dashboard build',23,True)
text(1485,829,'Plotly + Jinja2',18,fill=MUTED)
arrow([(1485,850),(1485,900)])
rect((1380,920,1590,987),'#24292F',r=12)
text(1485,953,'GitHub Pages',23,True,'white')
text(1485,1018,'Published static site',18,fill=MUTED)

text(80,944,'A model built for analysis',25,True,anchor='lm')
text(80,984,'One submission per extraction. Historical snapshots.',21,fill=MUTED,anchor='lm')
text(80,1017,'Gold powers the reporting queries and dashboard.',21,fill=MUTED,anchor='lm')

out=ROOT/'images/end-to-end-architecture.png'
im.save(out,optimize=True)
print(out)
