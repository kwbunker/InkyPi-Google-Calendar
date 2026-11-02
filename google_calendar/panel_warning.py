"""Draws a warning across the bottom of the calendar when it can't update.

Uses Pillow directly, not Chromium, so it still works if rendering is what failed.
"""
from PIL import ImageDraw

BANNER_COLOR = "#FF0000"
TEXT_COLOR = "#FFFFFF"
EDGE_COLOR = "#000000"


def add_warning_banner(image, message, last_updated, font):
    """Returns a copy of image with the warning added, leaving image itself unchanged."""
    result = image.convert("RGB")
    draw = ImageDraw.Draw(result)
    padding = font.size // 2
    lines = _wrap(draw, f"Calendar not updating: {message}", font, result.width - 2 * padding)
    if last_updated:
        lines.append(f"Last updated {last_updated}")

    line_height = font.size + font.size // 4
    top = result.height - (len(lines) * line_height + 2 * padding)
    draw.rectangle((0, top, result.width, result.height), fill=BANNER_COLOR)
    draw.line((0, top, result.width, top), fill=EDGE_COLOR, width=4)
    for index, line in enumerate(lines):
        draw.text((padding, top + padding + index * line_height), line, font=font, fill=TEXT_COLOR)
    return result


def _wrap(draw, text, font, max_width):
    lines = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines
