"""Render an example satellite table screenshot matching the dashboard theme."""

from PIL import Image, ImageDraw, ImageFont
import os

# ── Theme colors (from dashboard.css :root) ──
BG_PRIMARY = (15, 17, 23)        # #0f1117
BG_CARD = (26, 29, 39)           # #1a1d27
BORDER = (42, 45, 58)            # #2a2d3a
TEXT_PRIMARY = (228, 230, 239)   # #e4e6ef
TEXT_SECONDARY = (139, 143, 163) # #8b8fa3
TEXT_MUTED = (92, 96, 120)       # #5c6078

# Constellation colors
COLORS = {
    'GPS':     (74, 158, 255),   # #4a9eff
    'Galileo': (52, 211, 153),   # #34d399
    'GLONASS': (248, 113, 113),  # #f87171
    'BeiDou':  (251, 191, 36),   # #fbbf24
    'SBAS':    (167, 139, 250),  # #a78bfa
    'QZSS':    (251, 146, 60),   # #fb923c
}

# ── Layout constants ──
WIDTH = 900
ROW_HEIGHT = 56
HEADER_HEIGHT = 60
CARD_PAD = 28
CARD_RADIUS = 12
TITLE_AREA = 70
COL_X = [60, 260, 430, 640, 810]  # System, PRN, Elevation, Azimuth, SNR


def badge_bg(color, alpha=0.15):
    """Create semi-transparent badge background color blended onto card bg."""
    r = int(BG_CARD[0] * (1 - alpha) + color[0] * alpha)
    g = int(BG_CARD[1] * (1 - alpha) + color[1] * alpha)
    b = int(BG_CARD[2] * (1 - alpha) + color[2] * alpha)
    return (r, g, b)


def rounded_rect(draw, xy, radius, fill=None, outline=None, width=1):
    """Draw a rounded rectangle."""
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def try_load_font(size, bold=False):
    """Try to load a good font, fall back to default."""
    candidates = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold
        else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf' if bold
        else '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def try_load_mono(size):
    """Try to load a monospace font."""
    candidates = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf',
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


# ── Satellite data (after fix: Galileo shows correctly, PRNs normalized) ──
satellites = [
    # (system, prn, elevation, azimuth, snr, tracked)
    ('Galileo', 2,  59.0, 147.0, 32, True),
    ('Galileo', 3,  11.0,   3.0, 18, True),
    ('Galileo', 7,  35.0, 247.0, 28, True),
    ('Galileo', 8,  42.0, 317.0, 35, True),
    ('Galileo', 25, 14.0, 107.0, 22, True),
    ('Galileo', 30, 46.0, 247.0, 30, True),
    ('Galileo', 36, 32.0,  85.0, 26, True),
    ('GPS',     1,  14.0, 134.0, 21, True),
    ('GPS',     13, 40.0, 310.0, 38, True),
    ('GPS',     14, 43.0, 115.0, 36, True),
    ('GPS',     15, 25.0, 272.0, 29, True),
    ('GPS',     17, 68.0, 136.0, 42, True),
    ('GPS',     19, 12.0,  45.0, 15, True),
    ('GPS',     22, 55.0, 200.0, 33, True),
    ('GLONASS', 2,  38.0, 290.0, 27, True),
    ('GLONASS', 11, 22.0,  60.0, 19, True),
    ('GLONASS', 18, 50.0, 175.0, 31, True),
    ('BeiDou',  7,  30.0, 220.0, 24, True),
    ('BeiDou',  14, 45.0, 330.0, 34, True),
    ('SBAS',    135, 48.0, 345.0,  0, False),
    ('SBAS',    137, 49.0, 353.0,  0, False),
    ('QZSS',    2,  16.0, 350.0, 12, True),
    ('GPS',     6,   5.0, 180.0,  0, False),
    ('GLONASS', 24,  3.0, 310.0,  0, False),
    ('BeiDou',  21, 8.0,  95.0,   0, False),
]

num_rows = len(satellites)
visible = len(satellites)
tracked = sum(1 for s in satellites if s[5])

# ── Image dimensions ──
table_top = CARD_PAD + TITLE_AREA
table_height = HEADER_HEIGHT + ROW_HEIGHT * num_rows
card_height = TITLE_AREA + table_height + CARD_PAD
img_height = card_height + CARD_PAD * 2

img = Image.new('RGB', (WIDTH, img_height), BG_PRIMARY)
draw = ImageDraw.Draw(img)

# ── Fonts ──
font_title = try_load_font(16, bold=True)
font_badge_text = try_load_font(12)
font_header = try_load_font(13, bold=True)
font_cell = try_load_mono(14)
font_badge = try_load_font(12, bold=True)
font_snr_small = try_load_mono(12)

# ── Card background ──
card_x0, card_y0 = CARD_PAD, CARD_PAD
card_x1, card_y1 = WIDTH - CARD_PAD, img_height - CARD_PAD
rounded_rect(draw, (card_x0, card_y0, card_x1, card_y1),
             CARD_RADIUS, fill=BG_CARD, outline=BORDER)

# ── Title: "SATELLITES" + badge ──
title_x = card_x0 + 24
title_y = card_y0 + 22
draw.text((title_x, title_y), "SATELLITES", fill=TEXT_SECONDARY, font=font_title)

# Count badge
badge_text = f"{visible} visible, {tracked} tracked"
bbox = draw.textbbox((0, 0), badge_text, font=font_badge_text)
bw = bbox[2] - bbox[0] + 16
bh = bbox[3] - bbox[1] + 8
badge_x = title_x + draw.textbbox((0, 0), "SATELLITES", font=font_title)[2] + 14
badge_y = title_y + 1
badge_fill = badge_bg(COLORS['GPS'])
rounded_rect(draw, (badge_x, badge_y, badge_x + bw, badge_y + bh),
             10, fill=badge_fill, outline=(*COLORS['GPS'], 77), width=1)
draw.text((badge_x + 8, badge_y + 3), badge_text, fill=COLORS['GPS'], font=font_badge_text)

# ── Column headers ──
headers = ['SYSTEM', 'PRN', 'ELEVATION', 'AZIMUTH', 'SNR (dB-Hz)']
header_y = card_y0 + TITLE_AREA + 8
for i, hdr in enumerate(headers):
    draw.text((card_x0 + COL_X[i], header_y), hdr,
              fill=TEXT_SECONDARY, font=font_header)

# Header underline
line_y = header_y + 28
draw.line((card_x0 + 20, line_y, card_x1 - 20, line_y), fill=BORDER, width=2)

# ── Table rows ──
row_y_start = line_y + 8
for row_idx, (system, prn, elev, azim, snr, tracked_flag) in enumerate(satellites):
    y = row_y_start + row_idx * ROW_HEIGHT
    cell_y = y + 16

    # Row separator
    if row_idx > 0:
        sep_y = y + 2
        draw.line((card_x0 + 20, sep_y, card_x1 - 20, sep_y),
                  fill=(*BORDER, 77), width=1)

    # System badge
    color = COLORS.get(system, TEXT_MUTED)
    bg = badge_bg(color)
    bbox = draw.textbbox((0, 0), system, font=font_badge)
    bw = bbox[2] - bbox[0] + 16
    bh = bbox[3] - bbox[1] + 10
    bx = card_x0 + COL_X[0]
    by = cell_y - 3
    rounded_rect(draw, (bx, by, bx + bw, by + bh), 5, fill=bg)
    draw.text((bx + 8, by + 4), system, fill=color, font=font_badge)

    # PRN
    draw.text((card_x0 + COL_X[1], cell_y), str(prn),
              fill=TEXT_PRIMARY, font=font_cell)

    # Elevation
    draw.text((card_x0 + COL_X[2], cell_y), f"{elev:.1f}\u00b0",
              fill=TEXT_PRIMARY, font=font_cell)

    # Azimuth
    draw.text((card_x0 + COL_X[3], cell_y), f"{azim:.1f}\u00b0",
              fill=TEXT_PRIMARY, font=font_cell)

    # SNR bar
    snr_x = card_x0 + COL_X[4]
    if snr > 0:
        # SNR value
        draw.text((snr_x, cell_y), str(snr), fill=TEXT_PRIMARY, font=font_snr_small)
        # SNR bar background
        bar_x = snr_x + 30
        bar_y = cell_y + 4
        bar_w = 50
        bar_h = 6
        rounded_rect(draw, (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
                     3, fill=(30, 32, 42))
        # SNR bar fill
        fill_w = int(min(snr / 50, 1.0) * bar_w)
        if snr < 15:
            bar_color = COLORS['GLONASS']  # red
        elif snr < 25:
            bar_color = COLORS['BeiDou']   # yellow
        elif snr < 35:
            bar_color = COLORS['Galileo']  # green
        else:
            bar_color = COLORS['GPS']      # blue
        if fill_w > 0:
            rounded_rect(draw, (bar_x, bar_y, bar_x + fill_w, bar_y + bar_h),
                         3, fill=bar_color)
    else:
        draw.text((snr_x, cell_y), "-", fill=TEXT_MUTED, font=font_snr_small)

# ── Save ──
output_path = os.path.join(os.path.dirname(__file__), 'satellite_table_example.jpg')
img.save(output_path, 'JPEG', quality=95)
print(f"Saved: {output_path}")
print(f"Dimensions: {img.size[0]}x{img.size[1]}")
