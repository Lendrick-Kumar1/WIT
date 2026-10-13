"""Build synthetic words the way PyMuPDF returns them, so every rule can be tested without a PDF.

    line(y, (x, "text"), (x, "more text"))  -> words of one printed line at height y
Each word is ~5 pt per character wide and 10 pt high; words of one cell are 3 pt apart.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

CHAR_W, H, SPACE = 5.0, 10.0, 3.0


def line(y, *cells):
    words = []
    for x, text in cells:
        for t in text.split():
            words.append(dict(x0=x, y0=y, x1=x + CHAR_W * len(t), y1=y + H, t=t))
            x += CHAR_W * len(t) + SPACE
    return words


def lines(*ls):
    return [w for ln in ls for w in ln]


def table_words(header, rows, x=(10, 120, 230, 340, 450), y0=10, step=14):
    """header = [names]; rows = [[cells]] -> words of a simple table, one line per row."""
    words = line(y0, *[(x[k], h) for k, h in enumerate(header) if h])
    for i, r in enumerate(rows, 1):
        words += line(y0 + i * step, *[(x[k], c) for k, c in enumerate(r) if c])
    return words
