#!/usr/bin/env python3
"""Generate an animated GitHub contributions snake GIF.

Author: maatsuh

The snake walks a deterministic serpentine path across a GitHub
contribution grid, eats fruits on contribution cells and loops forever
with a seamless (perfect) loop.

Usage:
    python scripts/generate_snake.py --demo
    python scripts/generate_snake.py

Without --demo, GITHUB_TOKEN and GITHUB_OWNER environment variables
are required; the script falls back to demo data if they are missing.
"""

import argparse
import datetime as dt
import json
import math
import os
import random
import struct
import urllib.error
import urllib.request

from PIL import Image, ImageChops, ImageDraw, ImageFilter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_PATH = os.path.join(BASE_DIR, "output", "github-snake.gif")

# ------------------------------- CONFIG --------------------------------
CELL_SIZE = 20
CELL_GAP = 4
GRID_ROWS = 7
GRID_COLS = 52
PADDING = 26

SNAKE_LENGTH = 14
MOVEMENT_SPEED = 1.0
FPS = 12
FRAME_COUNT = 0
GLOW_SIZE = 8
GLOW_INTENSITY = 0.55
FRUIT_WINDOW = 20
SPARKLE_LIFE = 9
FOODS_PER_CYCLE = 8

BACKGROUND_COLOR = (13, 17, 23)
LEVEL_COLORS = [
    (17, 26, 38),
    (20, 36, 52),
    (22, 48, 74),
    (24, 62, 98),
    (27, 82, 132),
]
SNAKE_COLOR = (64, 255, 122)
SNAKE_TAIL_COLOR = (18, 92, 46)
BODY_OUTLINE = (12, 46, 26)
BODY_BELLY = (196, 255, 216)
BODY_RADIUS = 7.5
TAIL_END = 7.0
HEAD_COLOR = (148, 255, 180)
HEAD_BORDER = (6, 44, 22)
GLOW_COLOR = (46, 255, 98)
EYE_COLOR = (255, 255, 255)
PUPIL_COLOR = (12, 34, 20)
MOUTH_COLOR = (12, 34, 20)
FRUIT_BODY = (255, 84, 84)
FRUIT_HIGHLIGHT = (255, 150, 150)
FRUIT_STEM = (150, 100, 48)
FRUIT_LEAF = (84, 224, 110)
SPARKLE_COLORS = [(255, 246, 150), (198, 255, 96), (110, 255, 160), (70, 130, 90)]
# ------------------------------------------------------------------------


def build_track(rows, cols):
    track = []
    for col in range(cols):
        if col % 2 == 0:
            track.extend((row, col) for row in range(rows))
        else:
            track.extend((row, col) for row in range(rows - 1, -1, -1))
    for col in range(cols - 2, 0, -1):
        track.append((0, col))
    return track


def cell_center(row, col):
    x = PADDING + col * (CELL_SIZE + CELL_GAP) + CELL_SIZE / 2.0
    y = PADDING + row * (CELL_SIZE + CELL_GAP) + CELL_SIZE / 2.0
    return x, y


def canvas_size():
    w = 2 * PADDING + GRID_COLS * CELL_SIZE + (GRID_COLS - 1) * CELL_GAP
    h = 2 * PADDING + GRID_ROWS * CELL_SIZE + (GRID_ROWS - 1) * CELL_GAP
    return w, h


TRACK = build_track(GRID_ROWS, GRID_COLS)
CYCLE_LEN = len(TRACK)
CENTERS = [[cell_center(r, c) for c in range(GRID_COLS)] for r in range(GRID_ROWS)]


def frames_per_cell():
    return max(2, min(8, int(round(3.0 / MOVEMENT_SPEED))))


def total_frames():
    if FRAME_COUNT > 0:
        return max(1, round(FRAME_COUNT / CYCLE_LEN)) * CYCLE_LEN
    return frames_per_cell() * CYCLE_LEN


# ------------------------------- DATA -----------------------------------
def level_of(count):
    if count <= 0:
        return 0
    return min(4, 1 + (count - 1) // 3)


def build_demo_grid():
    rng = random.Random(0x5A17E ^ dt.date.today().toordinal())
    today = dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())
    grid = [[0] * GRID_COLS for _ in range(GRID_ROWS)]
    for col in range(GRID_COLS):
        week_start = monday - dt.timedelta(weeks=GRID_COLS - 1 - col)
        streak = rng.random() < 0.12
        for row in range(GRID_ROWS):
            day = week_start + dt.timedelta(days=row - 1)
            seasonal = 0.55 + 0.45 * math.cos(
                (day.timetuple().tm_yday - 190) / 365.0 * math.tau
            )
            weekend = 0.32 if day.weekday() >= 5 else 0.95
            count = max(0, int(rng.gauss(3.4 * weekend * seasonal, 1.5)))
            if streak and day.weekday() < 5:
                count += 4
            grid[row][col] = level_of(count)
    return grid


def build_grid_from_github(owner, token):
    end = dt.date.today()
    while end.weekday() != 5:
        end -= dt.timedelta(days=1)
    start = end - dt.timedelta(days=GRID_ROWS * GRID_COLS - 1)
    query = """query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}"""
    payload = json.dumps(
        {
            "query": query,
            "variables": {
                "login": owner,
                "from": start.strftime("%Y-%m-%dT00:00:00Z"),
                "to": end.strftime("%Y-%m-%dT23:59:59Z"),
            },
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "User-Agent": "github-snake-generator",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError("GitHub API HTTP %s: %s" % (exc.code, exc.read().decode()[:200])) from exc
    if "errors" in body:
        raise RuntimeError(body["errors"])
    try:
        weeks = body["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError("unexpected GitHub API response") from exc
    counts = {}
    for week in weeks:
        for day in week["contributionDays"]:
            counts[dt.date.fromisoformat(day["date"])] = day["contributionCount"]
    grid = [[0] * GRID_COLS for _ in range(GRID_ROWS)]
    for col in range(GRID_COLS):
        for row in range(GRID_ROWS):
            d = start + dt.timedelta(days=col * GRID_ROWS + row)
            grid[row][col] = level_of(counts.get(d, 0))
    return grid


# ------------------------------- FOOD -----------------------------------
def plan_foods(grid):
    good = []
    for i in range(GRID_COLS * GRID_ROWS):
        r, c = TRACK[i]
        if r >= 1 and grid[r][c] >= 1:
            good.append(i)
    if len(good) < FOODS_PER_CYCLE:
        good = [i for i in range(GRID_COLS * GRID_ROWS) if TRACK[i][0] >= 1]
    foods = []
    for k in range(FOODS_PER_CYCLE):
        target = 40 + k * (320.0 / max(1, FOODS_PER_CYCLE - 1))
        best = min(range(len(good)), key=lambda j: abs(good[j] - target))
        pick = good.pop(best)
        foods.append(
            {
                "cell": TRACK[pick],
                "eat": float(pick),
                "appear": float(pick) - FRUIT_WINDOW,
                "seed": pick * 7919,
            }
        )
    return foods


# ---------------------------- RENDERING ---------------------------------
def _ramp(c0, c1, n):
    return [tuple(int(c0[k] + (c1[k] - c0[k]) * t / n) for k in range(3)) for t in range(1, n + 1)]


def build_palette():
    colors = set(
        [
            BACKGROUND_COLOR,
            EYE_COLOR,
            PUPIL_COLOR,
            MOUTH_COLOR,
            FRUIT_STEM,
            FRUIT_LEAF,
        ]
    )
    for c in LEVEL_COLORS:
        colors.update(_ramp(BACKGROUND_COLOR, c, 4))
    colors.update(_ramp(BACKGROUND_COLOR, SNAKE_COLOR, 5))
    colors.update(_ramp(BACKGROUND_COLOR, SNAKE_TAIL_COLOR, 3))
    colors.update(_ramp(BACKGROUND_COLOR, BODY_BELLY, 4))
    colors.update(_ramp(BACKGROUND_COLOR, BODY_OUTLINE, 3))
    colors.update(_ramp(BACKGROUND_COLOR, HEAD_COLOR, 5))
    colors.update(_ramp(BACKGROUND_COLOR, GLOW_COLOR, 5))
    colors.update(_ramp(BACKGROUND_COLOR, FRUIT_BODY, 4))
    for c in SPARKLE_COLORS:
        colors.update(_ramp(BACKGROUND_COLOR, c, 3))
    ordered = sorted(colors)
    pal = Image.new("P", (1, 1))
    flat = [v for rgb in ordered for v in rgb]
    pal.putpalette(flat + [0] * (768 - len(flat)))
    return pal, len(ordered)


def render_background(grid, w2, h2, ss):
    img = Image.new("RGB", (w2, h2), BACKGROUND_COLOR)
    d = ImageDraw.Draw(img)
    radius = max(3, CELL_SIZE // 4) * ss
    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            x = PADDING + col * (CELL_SIZE + CELL_GAP)
            y = PADDING + row * (CELL_SIZE + CELL_GAP)
            d.rounded_rectangle(
                [x * ss, y * ss, (x + CELL_SIZE) * ss, (y + CELL_SIZE) * ss],
                radius=radius,
                fill=LEVEL_COLORS[grid[row][col]],
            )
    return img


def segment_at(p, i):
    q = (p - (SNAKE_LENGTH - 1 - i)) % CYCLE_LEN
    idx = int(q)
    f = q - idx
    r0, c0 = TRACK[idx]
    r1, c1 = TRACK[(idx + 1) % CYCLE_LEN]
    cx0, cy0 = CENTERS[r0][c0]
    cx1, cy1 = CENTERS[r1][c1]
    return (
        cx0 + (cx1 - cx0) * f,
        cy0 + (cy1 - cy0) * f,
        (r1 - r0, c1 - c0),
    )


def cell_rect_px(x, y, ss):
    s = CELL_SIZE * ss
    return [x * ss - s / 2.0, y * ss - s / 2.0, x * ss + s / 2.0, y * ss + s / 2.0]


def body_color(i):
    t = i / max(1, SNAKE_LENGTH - 2)
    return tuple(int(SNAKE_TAIL_COLOR[k] + (SNAKE_COLOR[k] - SNAKE_TAIL_COLOR[k]) * t) for k in range(3))


def chaikin_smooth(points, iters=2):
    pts = list(points)
    for _ in range(iters):
        out = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            out.append(((a[0] * 3 + b[0]) / 4.0, (a[1] * 3 + b[1]) / 4.0))
            out.append(((a[0] + b[0] * 3) / 4.0, (a[1] + b[1] * 3) / 4.0))
        out.append(pts[-1])
        pts = out
    return pts


def snake_geometry(p):
    n = SNAKE_LENGTH
    centers = [segment_at(p, i)[:2] for i in range(n)]
    radii = []
    for i in range(n):
        t = min(1.0, i / TAIL_END)
        r = 1.2 + (BODY_RADIUS - 1.2) * (t * t * (3.0 - 2.0 * t))
        if i >= n - 4:
            r *= 1.18
        radii.append(r)
    pts, rads = centers, radii
    for _ in range(2):
        out_p = [pts[0]]
        out_r = [rads[0]]
        for a, b, ra, rb in zip(pts, pts[1:], rads, rads[1:]):
            out_p.append(((a[0] * 3 + b[0]) / 4.0, (a[1] * 3 + b[1]) / 4.0))
            out_r.append((ra * 3 + rb) / 4.0)
            out_p.append(((a[0] + b[0] * 3) / 4.0, (a[1] + b[1] * 3) / 4.0))
            out_r.append((ra + rb * 3) / 4.0)
        out_p.append(pts[-1])
        out_r.append(rads[-1])
        pts, rads = out_p, out_r
    return pts, rads


def body_silhouette(p, ss, inflate=0.0):
    import math as _m
    pts, rads = snake_geometry(p)
    n = len(pts)
    L, R = [], []
    for i in range(n):
        a = pts[i - 1]
        b = pts[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = _m.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln, dx / ln
        r = (rads[i] + inflate) * ss
        L.append((pts[i][0] * ss + nx * r, pts[i][1] * ss + ny * r))
        R.append((pts[i][0] * ss - nx * r, pts[i][1] * ss - ny * r))
    return L + R[::-1]


def draw_fruit(draw, cell):
    r0, c0 = cell
    cx, cy = CENTERS[r0][c0]
    u = 2
    bx = int(round(cx - 1.5 * u))
    by = int(round(cy - 1.0 * u))
    draw.rectangle([bx, by, bx + 3 * u, by + 3 * u], fill=FRUIT_BODY)
    draw.rectangle([bx, by, bx + u, by + u], fill=FRUIT_HIGHLIGHT)
    sx = int(round(cx - 0.5 * u))
    draw.rectangle([sx, by - u, sx + u, by], fill=FRUIT_STEM)
    draw.rectangle([sx + u, by - u, sx + 2 * u, by], fill=FRUIT_LEAF)


def draw_sparkles(draw, fr, p, seed):
    r0, c0 = fr
    cx, cy = CENTERS[r0][c0]
    rng = random.Random(seed)
    idx = min(len(SPARKLE_COLORS) - 1, int(p * len(SPARKLE_COLORS)))
    color = SPARKLE_COLORS[idx]
    for _ in range(8):
        ang = rng.uniform(0.0, math.tau)
        dist = rng.uniform(1.2, 3.2) * p * CELL_SIZE * 0.55
        px = cx + math.cos(ang) * dist
        py = cy + math.sin(ang) * dist
        draw.rectangle([px - 1, py - 1, px + 1, py + 1], fill=color)


def draw_flash(draw, fr, grid, p):
    r0, c0 = fr
    cx, cy = CENTERS[r0][c0]
    base = LEVEL_COLORS[grid[r0][c0]]
    color = tuple(int(base[k] + (GLOW_COLOR[k] - base[k]) * 0.55 * (1.0 - p)) for k in range(3))
    radius = max(3, CELL_SIZE // 4)
    half = CELL_SIZE / 2.0
    draw.rounded_rectangle([cx - half, cy - half, cx + half, cy + half], radius=radius, fill=color)


def draw_face(draw2, hx, hy, direction):
    u = 2
    ox = hx - 5 * u
    oy = hy - 5 * u
    dr, dc = direction
    if dc > 0:
        eyes = [(5.5, 3.0), (5.5, 6.0)]
        pupils = [(6.5, 3.5), (6.5, 6.5)]
        mouth = (8.0, 4.5)
    elif dc < 0:
        eyes = [(2.5, 3.0), (2.5, 6.0)]
        pupils = [(2.5, 3.5), (2.5, 6.5)]
        mouth = (0.0, 4.5)
    elif dr > 0:
        eyes = [(3.0, 5.5), (6.0, 5.5)]
        pupils = [(3.5, 6.5), (6.5, 6.5)]
        mouth = (4.5, 8.0)
    else:
        eyes = [(3.0, 2.5), (6.0, 2.5)]
        pupils = [(3.5, 2.5), (6.5, 2.5)]
        mouth = (4.5, 0.0)
    for ex, ey in eyes:
        draw2.rectangle(
            [round(ox + ex * u), round(oy + ey * u), round(ox + (ex + 2) * u), round(oy + (ey + 2) * u)],
            fill=EYE_COLOR,
        )
    for px, py in pupils:
        draw2.rectangle(
            [round(ox + px * u), round(oy + py * u), round(ox + (px + 1) * u), round(oy + (py + 1) * u)],
            fill=PUPIL_COLOR,
        )
    mx, my = mouth
    draw2.rectangle(
        [round(ox + mx * u), round(oy + my * u), round(ox + (mx + 1) * u), round(oy + (my + 2) * u)],
        fill=MOUTH_COLOR,
    )


def render_frame(bg2x, p, foods, grid, ss):
    w2 = bg2x.width
    h2 = bg2x.height
    sil = body_silhouette(p, ss)
    glow = Image.new("L", (w2, h2), 0)
    gd = ImageDraw.Draw(glow)
    gd.polygon(sil, fill=255)
    glow = glow.filter(ImageFilter.GaussianBlur(GLOW_SIZE * ss))
    glow = glow.point([int(v * GLOW_INTENSITY) for v in range(256)])
    green = Image.new("RGB", (w2, h2), GLOW_COLOR)
    frame = Image.composite(green, bg2x, glow)
    draw = ImageDraw.Draw(frame)
    draw.polygon(sil, fill=SNAKE_COLOR)
    draw.polygon(body_silhouette(p, ss, inflate=-BODY_RADIUS * 0.45), fill=BODY_BELLY)
    draw.polygon(sil, outline=BODY_OUTLINE, width=ss)
    hx, hy, d = segment_at(p, SNAKE_LENGTH - 1)
    hh = (BODY_RADIUS * 1.5 + 1.5) * ss
    draw.ellipse(
        [hx * ss - hh, hy * ss - hh, hx * ss + hh, hy * ss + hh],
        fill=HEAD_COLOR,
        outline=BODY_OUTLINE,
        width=ss + 1,
    )
    frame = frame.resize((frame.width // ss, frame.height // ss), Image.Resampling.LANCZOS)
    d1 = ImageDraw.Draw(frame)
    for fr in foods:
        if fr["appear"] <= p < fr["eat"]:
            draw_fruit(d1, fr["cell"])
        elif fr["eat"] <= p < fr["eat"] + SPARKLE_LIFE:
            draw_sparkles(d1, fr["cell"], (p - fr["eat"]) / SPARKLE_LIFE, fr["seed"])
        elif fr["eat"] + SPARKLE_LIFE <= p < fr["eat"] + SPARKLE_LIFE + 5:
            draw_flash(d1, fr["cell"], grid, (p - fr["eat"] - SPARKLE_LIFE) / 5.0)
    draw_face(d1, hx, hy, d)
    return frame


# ---------------------------- GIF WRITER ---------------------------------
class DeltaGifWriter:
    def __init__(self, path, color_count, w, h, fps):
        self.f = open(path, "wb")
        self.w = w
        self.h = h
        self.bits = 2
        while (1 << self.bits) < color_count:
            self.bits += 1
        self.delay = max(1, int(round(100.0 / fps)))

    def close(self):
        self.f.write(b"\x3b")
        self.f.close()

    def header(self, palette):
        f = self.f
        f.write(b"GIF89a")
        f.write(struct.pack("<HH", self.w, self.h))
        f.write(bytes([0x80 | (self.bits - 1), 0, 0]))
        for rgb in palette:
            f.write(bytes(rgb))
        for _ in range((1 << self.bits) - len(palette)):
            f.write(b"\x00\x00\x00")
        f.write(b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00")

    def write_frame(self, x, y, w, h, indices):
        f = self.f
        f.write(b"\x21\xf9\x04\x04")
        f.write(struct.pack("<H", self.delay))
        f.write(b"\x00\x00")
        f.write(b"\x2c")
        f.write(struct.pack("<HHHH", x, y, w, h))
        f.write(b"\x00")
        f.write(bytes([self.bits]))
        f.write(self._lzw(indices))

    def _lzw(self, data):
        clear = 1 << self.bits
        eoi = clear + 1
        running = eoi + 1
        running_bits = self.bits + 1
        max_code1 = 1 << running_bits
        table = {}
        out = bytearray()
        acc = 0
        nbits = 0

        def emit(code):
            nonlocal acc, nbits, running_bits, max_code1
            acc |= code << nbits
            nbits += running_bits
            while nbits >= 8:
                out.append(acc & 0xFF)
                acc >>= 8
                nbits -= 8
            if running >= max_code1 and code <= 4095 and running_bits < 12:
                running_bits += 1
                max_code1 <<= 1

        emit(clear)
        cur = -1
        for b in data:
            if cur < 0:
                cur = b
                continue
            key = (cur << 8) | b
            code = table.get(key)
            if code is None:
                emit(cur)
                if running >= 4096:
                    emit(clear)
                    running = eoi + 1
                    running_bits = self.bits + 1
                    max_code1 = 1 << running_bits
                    table = {}
                else:
                    table[key] = running
                    running += 1
                cur = b
            else:
                cur = code
        if cur >= 0:
            emit(cur)
        emit(eoi)
        if nbits:
            out.append(acc & 0xFF)
        blocks = bytearray()
        for i in range(0, len(out), 255):
            chunk = bytes(out[i : i + 255])
            blocks.append(len(chunk))
            blocks.extend(chunk)
        blocks.append(0)
        return bytes(blocks)


# ------------------------------- MAIN ------------------------------------
def render_gif(grid, foods, out_path):
    ss = 2
    W, H = canvas_size()
    bg2x = render_background(grid, W * ss, H * ss, ss)
    pal, color_count = build_palette()
    fpc = frames_per_cell()
    total = total_frames()
    writer = DeltaGifWriter(out_path, color_count, W, H, FPS)
    writer.header([tuple(pal.getpalette()[i : i + 3]) for i in range(0, 3 * color_count, 3)])

    prev = None
    for i in range(total):
        p = i / fpc
        frame = render_frame(bg2x, p, foods, grid, ss)
        if prev is None:
            bbox = (0, 0, W, H)
        else:
            bbox = ImageChops.difference(prev, frame).getbbox()
        if bbox is not None:
            x0, y0, x1, y1 = bbox
            region = frame.crop(bbox)
            qi = region.quantize(palette=pal, dither=Image.Dither.NONE)
            writer.write_frame(x0, y0, x1 - x0, y1 - y0, qi.tobytes())
        prev = frame
        if (i + 1) % 120 == 0:
            print("  frame %d/%d" % (i + 1, total))
    writer.close()
    return os.path.getsize(out_path)


def main():
    parser = argparse.ArgumentParser(description="Generate an animated GitHub contributions snake GIF.")
    parser.add_argument("--demo", action="store_true", help="use fictional contributions (no token needed)")
    parser.add_argument("--output", default=OUTPUT_PATH, help="output GIF path")
    args = parser.parse_args()

    if args.demo:
        grid = build_demo_grid()
        source = "demo data"
    else:
        token = os.environ.get("GITHUB_TOKEN")
        owner = os.environ.get("GITHUB_OWNER")
        if token and owner:
            try:
                grid = build_grid_from_github(owner, token)
                source = "github.com/" + owner
            except Exception as exc:
                print("[warning] GitHub API request failed: %s" % exc)
                print("[warning] falling back to demo data")
                grid = build_demo_grid()
                source = "demo data (fallback)"
        else:
            print("[warning] GITHUB_TOKEN/GITHUB_OWNER not set; using demo data")
            grid = build_demo_grid()
            source = "demo data"

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    foods = plan_foods(grid)
    started = dt.datetime.now()
    size = render_gif(grid, foods, args.output)
    elapsed = (dt.datetime.now() - started).total_seconds()

    print()
    print("source       : %s" % source)
    print("grid         : %dx%d cells" % (GRID_COLS, GRID_ROWS))
    print("track        : %d cells (serpentine + return leg)" % CYCLE_LEN)
    print("frames       : %d at %d fps (perfect loop)" % (total_frames(), FPS))
    print("output       : %s" % os.path.abspath(args.output))
    print("size         : %.1f KiB" % (size / 1024.0))
    print("time         : %.1f s" % elapsed)


if __name__ == "__main__":
    main()