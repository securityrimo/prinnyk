from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parent
src=ROOT/'workspace/exports/prinny1_original_title_logo_extracted/original_anime00_object_078_group_00_page_00.png'
out=ROOT/'workspace/translations/generated_title_menu_korean.png'
im=Image.open(src).convert('RGBA'); d=ImageDraw.Draw(im)
for box in [(278,238,380,264),(278,264,380,289),(292,288,360,310),(407,108,505,130),(407,132,505,154)]: d.rectangle(box,fill=(0,0,0,0))
font=ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',16,index=0)
green=(0,255,0,255)
d.text((282,241),'처음부터',font=font,fill=green)
d.text((282,267),'이어하기',font=font,fill=green)
d.text((296,291),'설정',font=font,fill=green)
d.text((414,111),'데이터 로드',font=font,fill=green)
d.text((414,136),'데이터 교환',font=font,fill=green)
out.parent.mkdir(parents=True,exist_ok=True); im.save(out); print(out)
