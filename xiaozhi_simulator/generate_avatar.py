#!/usr/bin/env python3
"""Generate a cute xiaozhi robot avatar JPG using PIL."""

from PIL import Image, ImageDraw, ImageFont
import math


def create_xiaozhi_avatar(size=256, filename="avatar.jpg"):
    """Create a cute robot avatar for XiaoZhi."""
    img = Image.new("RGB", (size, size), color=(30, 30, 50))
    draw = ImageDraw.Draw(img)

    # Background gradient (dark blue to purple)
    for y in range(size):
        r = int(30 + (y / size) * 20)
        g = int(30 + (y / size) * 10)
        b = int(50 + (y / size) * 40)
        draw.line([(0, y), (size, y)], fill=(r, g, b))

    cx, cy = size // 2, size // 2

    # Outer glow
    for r in range(size // 2 + 20, size // 2 - 10, -2):
        alpha = int(40 * (1 - (size // 2 + 20 - r) / 30))
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            outline=(100, 180, 255, alpha) if hasattr(draw, 'rgba') else (100, 180, 255),
            width=1,
        )

    # Head
    head_r = size // 3
    draw.ellipse(
        [cx - head_r, cy - head_r - 10, cx + head_r, cy + head_r],
        fill=(60, 80, 140),
        outline=(140, 200, 255),
        width=3,
    )

    # Antenna
    draw.line([(cx, cy - head_r - 10), (cx, cy - head_r - 35)], fill=(180, 220, 255), width=4)
    draw.ellipse(
        [cx - 8, cy - head_r - 45, cx + 8, cy - head_r - 29],
        fill=(255, 100, 100),
        outline=(255, 150, 150),
        width=1,
    )

    # Eyes
    eye_y = cy - 15
    eye_offset = head_r // 3
    eye_r = head_r // 5

    # Eye whites
    for dx in [-eye_offset, eye_offset]:
        draw.ellipse(
            [cx + dx - eye_r - 2, eye_y - eye_r - 2, cx + dx + eye_r + 2, eye_y + eye_r + 2],
            fill=(240, 245, 255),
        )
        # Pupils
        pupil_r = eye_r // 2
        draw.ellipse(
            [cx + dx - pupil_r, eye_y - pupil_r, cx + dx + pupil_r, eye_y + pupil_r],
            fill=(30, 50, 80),
        )
        # Eye shine
        shine_r = pupil_r // 2
        draw.ellipse(
            [
                cx + dx + pupil_r // 2 - shine_r,
                eye_y - pupil_r - shine_r,
                cx + dx + pupil_r // 2 + shine_r,
                eye_y - pupil_r + shine_r,
            ],
            fill=(255, 255, 255),
        )

    # Blush
    blush_y = cy + 15
    blush_offset = head_r // 2 + 5
    for dx in [-blush_offset, blush_offset]:
        draw.ellipse(
            [cx + dx - 12, blush_y - 6, cx + dx + 12, blush_y + 8],
            fill=(255, 150, 150, 100) if hasattr(draw, 'rgba') else (255, 150, 150),
        )

    # Mouth (smile)
    mouth_y = cy + 25
    draw.arc(
        [cx - 20, mouth_y - 10, cx + 20, mouth_y + 15],
        start=0,
        end=180,
        fill=(255, 200, 200),
        width=2,
    )

    # Body
    body_top = cy + head_r + 5
    body_w, body_h = head_r + 20, head_r + 10
    draw.rounded_rectangle(
        [cx - body_w // 2, body_top, cx + body_w // 2, body_top + body_h],
        radius=12,
        fill=(50, 70, 130),
        outline=(140, 200, 255),
        width=2,
    )

    # Chest LED / heart
    heart_y = body_top + body_h // 2
    heart_size = 12
    # Simple heart shape
    heart_points = [
        (cx, heart_y + heart_size // 2),
        (cx - heart_size, heart_y - heart_size // 3),
        (cx - heart_size // 2, heart_y - heart_size),
        (cx, heart_y - heart_size // 2),
        (cx + heart_size // 2, heart_y - heart_size),
        (cx + heart_size, heart_y - heart_size // 3),
    ]
    draw.polygon(heart_points, fill=(255, 80, 80), outline=(255, 130, 130))

    # Ears / side modules
    ear_y = cy - 5
    ear_size = 15
    for dx in [-(head_r + 8), head_r + 8]:
        draw.rounded_rectangle(
            [cx + dx - ear_size, ear_y - ear_size, cx + dx + ear_size, ear_y + ear_size],
            radius=6,
            fill=(80, 100, 160),
            outline=(140, 200, 255),
            width=2,
        )

    # WiFi waves (top right)
    wifi_x, wifi_y = size - 35, 30
    for i in range(3):
        arc_r = 8 + i * 6
        draw.arc(
            [wifi_x - arc_r, wifi_y - arc_r // 2, wifi_x + arc_r, wifi_y + arc_r],
            start=220,
            end=320,
            fill=(100, 220, 100),
            width=2,
        )

    # Battery icon (top left)
    bat_x, bat_y = 25, 25
    draw.rectangle([bat_x, bat_y, bat_x + 30, bat_y + 14], outline=(100, 220, 100), width=2)
    draw.rectangle([bat_x + 2, bat_y + 2, bat_x + 26, bat_y + 12], fill=(100, 220, 100))
    draw.rectangle([bat_x + 30, bat_y + 4, bat_x + 33, bat_y + 10], fill=(100, 220, 100))

    # "小智" text
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 20)
        except (OSError, IOError):
            font = ImageFont.load_default()

    # Draw text at bottom
    text = "小智 AI"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text((cx - tw // 2, size - 35), text, fill=(180, 220, 255), font=font)

    # Version text
    ver_text = "v2.2.6"
    try:
        small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
    except (OSError, IOError):
        small_font = ImageFont.load_default()
    draw.text((cx - 20, size - 18), ver_text, fill=(120, 150, 200), font=small_font)

    img.save(filename, "JPEG", quality=92)
    print(f"Avatar saved to {filename} ({size}x{size})")
    return img


if __name__ == "__main__":
    create_xiaozhi_avatar()
