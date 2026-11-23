"""Một video liền mạch: máy quay đi lần lượt qua từng gian, không cắt cảnh."""
import sys, subprocess, math
sys.path.insert(0, '.')
from regions import REGIONS
from PIL import Image, ImageDraw, ImageFont
SRC, OUT = sys.argv[1], sys.argv[2]
W = H = 720; FPS = 30; UP = 3; N = 736
TRAVEL, HOLD, INTRO, OUTRO = 2.2, 3.6, 2.0, 3.0
# Lộ trình đi bộ: vào cổng, vòng ngược chiều kim đồng hồ, kết thúc ở chính đường
ORDER = ["01", "02", "03", "06", "08", "09", "10", "07", "04", "05"]
R = {r[0][:2]: r for r in REGIONS}
stops = [R[k] for k in ORDER]

src = Image.open(SRC).convert('RGB')
big = src.resize((N*UP, N*UP), Image.LANCZOS)
MM = 150; mini = src.resize((MM, MM), Image.LANCZOS)
fT = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf', 44)
fD = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 24)
fS = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 18)
grad = Image.new('L', (1, 200))
for y in range(200): grad.putpixel((0, y), int(215*(y/199)**1.4))
grad = grad.resize((W, 200))

ease = lambda t: (lambda u: u*u*(3-2*u))(max(0, min(1, t)))
lerp = lambda a, b, t: a + (b-a)*t

def clamp(cx, cy, s):
    s = min(s, N); return min(max(cx, s/2), N-s/2), min(max(cy, s/2), N-s/2), s

def view(cx, cy, s):
    cx, cy, s = clamp(cx, cy, s)
    return big.transform((W, H), Image.EXTENT,
        [(cx-s/2)*UP, (cy-s/2)*UP, (cx+s/2)*UP, (cy+s/2)*UP], Image.BICUBIC), (cx, cy, s)

def overlay(fr, cam, cap, a_cap, a_map):
    ov = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    if cap and a_cap > 0:
        idx, title, desc = cap; c = int(255*a_cap)
        sh = Image.new('RGBA', (W, 200), (12, 8, 4, 255)); sh.putalpha(grad.point(lambda v: int(v*a_cap)))
        ov.paste(sh, (0, H-200), sh)
        d.text((40, H-152), f'GIAN {idx:02d} / {len(stops):02d}', font=fS, fill=(214, 178, 110, c))
        d.text((40, H-125), title, font=fT, fill=(250, 244, 230, c))
        d.text((42, H-66), desc, font=fD, fill=(230, 220, 200, c))
    if a_map > 0:   # bản đồ nhỏ góc trên phải
        x0, y0 = W-MM-20, 20; m = mini.copy().convert('RGBA'); m.putalpha(int(235*a_map))
        d.rectangle((x0-3, y0-3, x0+MM+2, y0+MM+2), fill=(12, 8, 4, int(200*a_map)))
        ov.paste(m, (x0, y0), m)
        cx, cy, s = cam; k = MM/N
        d.rectangle((x0+(cx-s/2)*k, y0+(cy-s/2)*k, x0+(cx+s/2)*k, y0+(cy+s/2)*k),
                    outline=(240, 200, 120, int(255*a_map)), width=2)
    return Image.alpha_composite(fr.convert('RGBA'), ov).convert('RGB')

# Dựng timeline các đoạn (thời gian bắt đầu, độ dài, loại, dữ liệu)
segs, t = [], 0.0
full = (N/2, N/2, N)
prev = full
segs.append((t, INTRO, 'hold_full', None)); t += INTRO
for i, (slug, title, desc, cx, cy, sz) in enumerate(stops, 1):
    tgt = (cx, cy, sz)
    segs.append((t, TRAVEL, 'travel', (prev, tgt))); t += TRAVEL
    segs.append((t, HOLD, 'hold', (tgt, i, title, desc))); t += HOLD
    prev = (cx + math.cos(i)*sz*0.05, cy + math.sin(i)*sz*0.04, sz*0.85)  # điểm kết thúc drift
segs.append((t, OUTRO, 'travel_out', (prev, full))); t += OUTRO
TOTAL = t

def camera(tt):
    for st, du, kind, data in segs:
        if tt < st + du or (st, du, kind, data) == segs[-1]:
            k = (tt - st)/du; break
    if kind == 'hold_full':
        return full, None, 0, ease(k*2-1)
    if kind in ('travel', 'travel_out'):
        (ax, ay, as_), (bx, by, bs) = data; e = ease(k)
        dist = math.hypot(bx-ax, by-ay)
        bump = 0 if kind == 'travel_out' else min(dist*0.45, 160)*math.sin(math.pi*e)
        return (lerp(ax, bx, e), lerp(ay, by, e), lerp(as_, bs, e) + bump), None, 0, 1 - (ease(k*1.5) if kind == 'travel_out' else 0)
    (cx, cy, sz), i, title, desc = data; e = ease(k)
    cam = (cx + math.cos(i)*sz*0.05*e, cy + math.sin(i)*sz*0.04*e, sz*lerp(1, 0.85, e))
    a = ease(k/0.18) * (1 - ease((k-0.86)/0.14))
    return cam, (i, title, desc), a, 1

p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
    '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
    '-crf', '20', '-preset', 'medium', '-movflags', '+faststart', OUT], stdin=subprocess.PIPE)
for f in range(int(TOTAL*FPS)):
    tt = f/FPS
    cam, cap, a_cap, a_map = camera(tt)
    fr, cam = view(*cam)
    fr = overlay(fr, cam, cap, a_cap, a_map)
    fade = min(1, tt/0.5, (TOTAL-tt)/0.5)
    if fade < 1: fr = Image.blend(Image.new('RGB', (W, H)), fr, max(0, fade))
    p.stdin.write(fr.tobytes())
p.stdin.close(); p.wait(); print('done', OUT, round(TOTAL, 1), 's')
