import sys, subprocess, math
sys.path.insert(0, '.')
from regions import REGIONS
from PIL import Image, ImageDraw, ImageFont, ImageFilter
SRC = sys.argv[1]; OUT = sys.argv[2]
W = H = 720; FPS = 30; DUR = 9.0; UP = 3
src = Image.open(SRC).convert('RGB')
big = src.resize((src.width*UP, src.height*UP), Image.LANCZOS)
fT = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf', 44)
fD = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 24)
fS = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 18)
grad = Image.new('L', (1, 200))
for y in range(200): grad.putpixel((0, y), int(215 * (y/199)**1.4))
grad = grad.resize((W, 200))

def ease(t): t = max(0, min(1, t)); return t*t*(3-2*t)
def lerp(a, b, t): return a + (b-a)*t

def view(cx, cy, s):
    s = min(s, 736); cx = min(max(cx, s/2), 736-s/2); cy = min(max(cy, s/2), 736-s/2)
    box = [(cx-s/2)*UP, (cy-s/2)*UP, (cx+s/2)*UP, (cy+s/2)*UP]
    return big.transform((W, H), Image.EXTENT, box, Image.BICUBIC)

def caption(fr, idx, title, desc, a):
    if a <= 0: return fr
    ov = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    shade = Image.new('RGBA', (W, 200), (12, 8, 4, 255)); shade.putalpha(grad.point(lambda v: int(v*a)))
    ov.paste(shade, (0, H-200), shade)
    d = ImageDraw.Draw(ov); c = int(255*a)
    d.text((40, H-150), f'GIAN {idx:02d} / {len(REGIONS):02d}', font=fS, fill=(214, 178, 110, c))
    d.text((40, H-125), title, font=fT, fill=(250, 244, 230, c))
    d.text((42, H-66), desc, font=fD, fill=(230, 220, 200, c))
    d.line((40, H-131, 40+int(120*a), H-131), fill=(214, 178, 110, c), width=2)
    return Image.alpha_composite(fr.convert('RGBA'), ov).convert('RGB')

for i, (slug, title, desc, cx, cy, sz) in enumerate(REGIONS, 1):
    out = f'{OUT}/{slug}.mp4'
    p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
        '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-crf', '18', '-preset', 'medium', '-movflags', '+faststart', out], stdin=subprocess.PIPE)
    n = int(DUR*FPS)
    for f in range(n):
        t = f / FPS
        if t < 2.5:   # bay từ toàn cảnh vào gian nhà
            k = ease(t/2.5); s = lerp(736, sz, k); x = lerp(368, cx, k); y = lerp(368, cy, k)
        else:         # trôi chậm và đẩy cận
            k = ease((t-2.5)/(DUR-2.5)); s = sz*lerp(1, 0.78, k)
            ang = i*0.9; x = cx + math.cos(ang)*sz*0.08*k; y = cy + math.sin(ang)*sz*0.06*k
        fr = view(x, y, s)
        a = ease((t-2.0)/0.8) * (1 - ease((t-(DUR-0.6))/0.6))
        fr = caption(fr, i, title, desc, a)
        fade = min(1, t/0.4, (DUR-t)/0.4)
        if fade < 1: fr = Image.blend(Image.new('RGB', (W, H)), fr, max(0, fade))
        p.stdin.write(fr.tobytes())
    p.stdin.close(); p.wait(); print('done', out)
