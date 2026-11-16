import json, pymupdf, re  

PDF = r"C:\Users\robin\Downloads\Learn-and-Master-Guitar-Lesson-Book.pdf"
OFFSET = 3  # printed page = pdf page - 3 (verified on 5 pages)
TOC_PDF_PAGE = 4    # 1-based

SESSION_RE = re.compile(r"^(\d{1,2})\)\s*(.+?)\s*$")
SONG_RE = re.compile(r"^(.+?)\s*\(CD\s*#(\d+)\s*Tr(?:acks?)?\.?\s*([\d,\s]+)\)\s*$")
PAGE_RE = re.compile(r"^\d{1,3}$")
SKIP = {"Table of Contents", "SESSIONS", "PAGE"}

doc = pymupdf.open(PDF)
with open("pages.jsonl", "w", encoding="utf-8") as out:
    for i, page in enumerate(doc):
        text = page.get_text()
        record = {
            "pdf_page": i + 1,
            "printed_page": (i + 1) - OFFSET if i + 1 > OFFSET else None,
            "char_count": len(text),
            "image_count": len(page.get_images()),
            "vector_paths": len(page.get_drawings()),
            "text": text,
        }
        out.write(json.dumps(record) + "\n")
print("Wrote", len(doc), "pages")

def parse_toc(text):
    lines = [l.strip() for l in text.splitlines() if l.strip() and l.strip() not in SKIP]
    sessions, current, i = [], None, 0
    while i < len(lines):
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        m_sess, m_song = SESSION_RE.match(line), SONG_RE.match(line)

        if m_sess and PAGE_RE.match(nxt):
            current = {"session": int(m_sess.group(1)), "title": m_sess.group(2).strip(),
                       "printed_page": int(nxt), "topics": [], "songs": []}
            sessions.append(current); i += 2
        elif m_song and PAGE_RE.match(nxt) and current:
            current["songs"].append({"title": m_song.group(1).strip(),
                                     "cd": int(m_song.group(2)),
                                     "tracks": m_song.group(3).replace(" ", ""),
                                     "printed_page": int(nxt)})
            i += 2
        elif current and not current["songs"]:
            current["topics"].append(line); i += 1
        else:
            i += 1

    for s in sessions:
        s["topics"] = " ".join(s["topics"])
        s["pdf_page"] = s["printed_page"] + OFFSET
    return sessions

doc = pymupdf.open(PDF)
sessions = parse_toc(doc[TOC_PDF_PAGE - 1].get_text())

# each session runs until the next one starts
ends = [s["pdf_page"] for s in sessions[1:]] + [len(doc) + 1]
for s, end in zip(sessions, ends):
    s["pdf_page_end"] = end - 1

json.dump(sessions, open("toc.json", "w"), indent=2)
print(f"Parsed {len(sessions)} sessions, {sum(len(s['songs']) for s in sessions)} songs")

BODY_START, BODY_END = 5, 108     # pdf pages: TOC is p4, acknowledgments p109

# font family + rounded size -> heading level
LEVELS = {28: "song", 20: "section", 18: "section", 14: "subsection"}

def heading_level(span):
    if "MediumCond" not in span["font"] and "CondensedB" not in span["font"]:
        return None
    return LEVELS.get(round(span["size"]))

def clean(t):
    return re.sub(r"\s+", " ", t).strip()

def find_headings(doc):
    found = []
    for pi in range(BODY_START - 1, BODY_END):
        items = []
        for b in doc[pi].get_text("dict")["blocks"]:
            for line in b.get("lines", []):
                for s in line["spans"]:
                    lvl = heading_level(s)
                    if lvl and s["text"].strip():
                        x0, y0, x1, y1 = s["bbox"]
                        items.append({"level": lvl, "size": round(s["size"]),
                                      "text": s["text"], "x0": x0, "x1": x1, "y0": y0, "y1": y1})
        items.sort(key=lambda i: (round(i["y0"]), i["x0"]))
        merged = []
        for it in items:
            prev = merged[-1] if merged else None
            same_line = prev and prev["size"] == it["size"] and abs(prev["y0"] - it["y0"]) < 3 \
                and 0 <= it["x0"] - prev["x1"] < it["size"]
            aligned = prev and (abs(prev["x0"] - it["x0"]) < 6 or
                                abs((prev["x0"] + prev["x1"]) / 2 - (it["x0"] + it["x1"]) / 2) < 6)
            # compare line TOPS (boxes can overlap): next line sits ~1.0-1.4x font size below
            wrapped = prev and prev["size"] == it["size"] and aligned \
                and 0 < it["y0"] - prev["last_y0"] < 1.4 * it["size"]
            if same_line or wrapped:
                prev["text"] += " " + it["text"]
                prev["x1"], prev["y1"] = max(prev["x1"], it["x1"]), max(prev["y1"], it["y1"])
                prev["last_y0"] = it["y0"]
            else:
                merged.append(dict(it, last_y0=it["y0"]))
        for m in merged:
            m["text"] = clean(m["text"])
            m["pdf_page"] = pi + 1
            m["printed_page"] = pi + 1 - OFFSET
        found.extend(merged)
    return found

doc = pymupdf.open(PDF)
heads = find_headings(doc)
json.dump(heads, open("headings.json", "w"), indent=1)
print(len(heads), "headings")

import pathlib, pymupdf

OUT = pathlib.Path("page_images"); OUT.mkdir(exist_ok=True)
doc = pymupdf.open(PDF)
for i, page in enumerate(doc):
    pix = page.get_pixmap(dpi=100)
    pix.save(OUT / f"page_{i+1:03d}.png")   # named by PDF page number
print("rendered", len(doc), "pages")