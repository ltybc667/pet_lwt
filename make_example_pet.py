"""Generate a tiny original animated sample pet for public releases."""

from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "pets" / "ExampleCat.gif"
frames = []
for step in range(6):
    im = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    bob = [0, -1, -2, -1, 0, 1][step]
    tail = [94, 99, 103, 99, 94, 90][step]
    d.line([(87, 91 + bob), (tail, 73 + bob), (109, 65 + bob)], fill="#54416f", width=9, joint="curve")
    d.ellipse((28, 53 + bob, 91, 117 + bob), fill="#7566aa", outline="#41375f", width=3)
    d.polygon([(31, 64 + bob), (28, 28 + bob), (51, 45 + bob)], fill="#7566aa", outline="#41375f")
    d.polygon([(70, 45 + bob), (89, 28 + bob), (89, 64 + bob)], fill="#7566aa", outline="#41375f")
    d.ellipse((27, 42 + bob, 90, 99 + bob), fill="#9484c7", outline="#41375f", width=3)
    if step == 3:
        d.arc((42, 70 + bob, 51, 77 + bob), 0, 180, fill="#27213c", width=2)
        d.arc((68, 70 + bob, 77, 77 + bob), 0, 180, fill="#27213c", width=2)
    else:
        d.ellipse((45, 69 + bob, 50, 77 + bob), fill="#27213c")
        d.ellipse((69, 69 + bob, 74, 77 + bob), fill="#27213c")
    d.polygon([(57, 80 + bob), (62, 80 + bob), (60, 84 + bob)], fill="#eb9bb2")
    d.arc((54, 82 + bob, 66, 90 + bob), 0, 180, fill="#41375f", width=2)
    frames.append(im)
frames[0].save(OUT, save_all=True, append_images=frames[1:], duration=[280] * 6, loop=0, disposal=2, transparency=0)
print(OUT)
