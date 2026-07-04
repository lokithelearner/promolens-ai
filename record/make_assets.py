import os
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.abspath(__file__))
FR = os.path.join(BASE, "frames"); SEQ = os.path.join(BASE, "seq")
os.makedirs(SEQ, exist_ok=True)
W, H = 1280, 720
NAVY = (22, 38, 79); NAVY2 = (31, 53, 104); RED = (226, 59, 78); WHITE = (255, 255, 255)
MUT = (168, 192, 234)

def font(sz, bold=True):
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return ImageFont.truetype(path, sz)

def fit_frame(src, dst, caption=None):
    im = Image.open(src).convert("RGB")
    canvas = Image.new("RGB", (W, H), (244, 246, 251))
    r = min(W / im.width, H / im.height)
    nw, nh = int(im.width * r), int(im.height * r)
    im = im.resize((nw, nh), Image.LANCZOS)
    canvas.paste(im, ((W - nw) // 2, (H - nh) // 2))
    if caption:
        d = ImageDraw.Draw(canvas, "RGBA")
        bar_h = 60
        d.rectangle([0, H - bar_h, W, H], fill=(22, 38, 79, 235))
        d.rectangle([0, H - bar_h, 6, H], fill=(226, 59, 78, 255))
        fnt = font(22, False)
        tw = d.textlength(caption, font=fnt)
        d.text(((W - tw) / 2, H - bar_h + (bar_h - 26) / 2), caption, font=fnt, fill=(255, 255, 255, 255))
    canvas.save(dst)

def center(d, text, y, fnt, fill):
    w = d.textlength(text, font=fnt); d.text(((W - w) / 2, y), text, font=fnt, fill=fill)

def gradient_bg():
    bg = Image.new("RGB", (W, H), NAVY)
    top = NAVY2
    for y in range(H):
        t = y / H
        c = tuple(int(top[i] + (NAVY[i] - top[i]) * t) for i in range(3))
        ImageDraw.Draw(bg).line([(0, y), (W, y)], fill=c)
    return bg

# intro card
intro = gradient_bg(); d = ImageDraw.Draw(intro)
d.rounded_rectangle([W/2-150, 150, W/2+150, 196], radius=23, fill=RED)
center(d, "GEN AI ACADEMY APAC 2026", 162, font(15), WHITE)
center(d, "PromoLens AI", 250, font(78), WHITE)
# red 'AI' accent
name_w = d.textlength("PromoLens AI", font=font(78))
ai_w = d.textlength("AI", font=font(78))
d.text(((W+ name_w)/2 - ai_w, 250), "AI", font=font(78), fill=RED)
center(d, "Trade Promotion Intelligence Copilot", 350, font(30, False), MUT)
center(d, "Stop burning crores on promotions you can't measure.", 410, font(20, False), (205, 217, 242))
center(d, "Built on Google Cloud  ·  Gemini 2.5  ·  BigQuery  ·  Vertex AI  ·  Cloud Run", 520, font(18), MUT)
intro.save(os.path.join(SEQ, "00_intro.png"))

# outro card
outro = gradient_bg(); d = ImageDraw.Draw(outro)
center(d, "PromoLens AI", 240, font(64), WHITE)
ai_w = d.textlength("AI", font=font(64)); name_w = d.textlength("PromoLens AI", font=font(64))
d.text(((W+name_w)/2 - ai_w, 240), "AI", font=font(64), fill=RED)
center(d, "Ask your promotion data anything — get the number, and the next move.", 340, font(21, False), MUT)
center(d, "BigQuery · Cloud Run · Gemini 2.5 · Google ADK · Vertex AI vector search · Gemini Vision", 430, font(16), MUT)
center(d, "© 2026 Lokesh Kadyan", 500, font(18), (205, 217, 242))
outro.save(os.path.join(SEQ, "99_outro.png"))

# scale frames in order, baking a lower-third caption into each
order = ["f01_top","f02_needs","f03_needs2","f04_wins","f05_chat","f06_fy","f07_fy_schemes","f08_report","f09_claim","f10_end"]
CAPS = [
    "Promotion ROI, leakage & scheme health — one screen, no spreadsheets",
    "Ranked by money at stake — what needs you",
    "Over-claims & inventory loading, flagged with the Rs at risk",
    "Clear wins to scale — return per Rs 1 spent",
    "Ask Me Anything — Gemini 2.5, grounded in an auditable engine",
    "Switch timeline — rolling 12 months or any financial year",
    "The whole cockpit recomputes for the chosen year",
    "One-click leadership report, written by Gemini",
    "Multimodal claim check — Gemini Vision flags over-claims",
    "Built on Google Cloud — Gemini 2.5 · BigQuery · Vertex AI · Cloud Run",
]
for i, (name, cap) in enumerate(zip(order, CAPS), 1):
    fit_frame(os.path.join(FR, name + ".png"), os.path.join(SEQ, f"{i:02d}.png"), cap)

# durations (seconds) — intro + 10 frames + outro = 134s (audio is 128s, starts at 3s)
durs = [("00_intro.png", 3), ("01.png", 20), ("02.png", 10), ("03.png", 10), ("04.png", 13),
        ("05.png", 18), ("06.png", 9), ("07.png", 8), ("08.png", 14), ("09.png", 16),
        ("10.png", 10), ("99_outro.png", 3)]
with open(os.path.join(BASE, "list.txt"), "w") as f:
    for fn, dur in durs:
        f.write(f"file '{os.path.join(SEQ, fn)}'\nduration {dur}\n")
    f.write(f"file '{os.path.join(SEQ, '99_outro.png')}'\n")  # concat demuxer needs last repeated

# captions (lower-third titles), offset +3s for the intro
caps = [
    (3, 23,  "Promotion ROI, leakage & scheme health — one screen, no spreadsheets"),
    (23, 33, "Ranked by money at stake — what needs you"),
    (33, 43, "Over-claims & inventory loading, flagged with the Rs at risk"),
    (43, 56, "Clear wins to scale — return per Rs 1 spent"),
    (56, 74, "Ask Me Anything — Gemini 2.5, grounded in an auditable engine"),
    (74, 83, "Switch timeline — rolling 12 months or any financial year"),
    (83, 91, "The whole cockpit recomputes for the chosen year"),
    (91, 105, "One-click leadership report, written by Gemini"),
    (105, 121, "Multimodal claim check — Gemini Vision flags over-claims"),
    (121, 131, "PromoLens AI — built on Google Cloud"),
]
def ts(s):
    h = int(s // 3600); m = int((s % 3600) // 60); sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:06.3f}".replace(".", ",")
with open(os.path.join(BASE, "captions.srt"), "w") as f:
    for i, (a, b, txt) in enumerate(caps, 1):
        f.write(f"{i}\n{ts(a)} --> {ts(b)}\n{txt}\n\n")
print("assets ready")
