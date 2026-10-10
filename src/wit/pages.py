"""Which pages feed which output. Plug your legacy key terms into config `pages:`.

pages:
  performance: ["Executive Summary", "Par Value Tests", ...]   # regexes
  balance:     [...]
  collateral:  ["Detail of Assets", "Detail of Ratings", ...]
  match_on: title        # 'title' = top band of the page (section name), 'text' = anywhere on page

An empty list means: scan every page (slower but safe; ~30 ms/page).
"""
import re

from .pdfpage import page_model, page_title, rows_of


_CACHE = {}


def page_texts(doc, title_band=0.2):
    key = (doc.name, title_band)
    if key in _CACHE:
        return _CACHE[key]
    out = []
    for p in doc:
        words = page_model(p)[0]
        out.append(dict(title=page_title(p, words, title_band),
                        text=" ".join(r["text"] for r in rows_of(words))))
    _CACHE.clear()
    _CACHE[key] = out
    return out


def select_pages(doc, cfg, output):
    pats = (cfg.get("pages") or {}).get(output) or []
    if not pats:
        return list(range(len(doc)))
    on = (cfg.get("pages") or {}).get("match_on", "title")
    texts = page_texts(doc, cfg.get("layout", {}).get("title_band", 0.2))
    keep = []
    for i, t in enumerate(texts):
        hay = t["title"] if on == "title" else t["text"]
        if any(re.search(p, hay, re.I) for p in pats):
            keep.append(i)
    return keep
