import json, re, pymupdf

PDF = r"C:\Users\robin\Downloads\Learn-and-Master-Guitar-Lesson-Book.pdf"
OFFSET = 3
BODY_START, BODY_END = 5, 108
MIN_CHARS, MAX_CHARS = 400, 1200
MIN_BODY_TO_EMBED = 60       # less body text than this -> metadata-only record


def clean_text(t):
    t = re.sub(r"(\w)-\s*\n\s*([a-z])", r"\1\2", t)   # re-join "repro-\nduced" (lowercase only)
    return re.sub(r"\s+", " ", t).strip()


def overlap(a0, a1, b0, b1):
    return max(0, min(a1, b1) - max(a0, b0))


# ---- Step A: give every heading the body text that belongs to it -------------
def assign_text(doc, heads):
    units = [dict(h, body=[]) for h in heads]
    for pi in range(BODY_START - 1, BODY_END):
        page_no = pi + 1
        page_units = [u for u in units if u["pdf_page"] == page_no]
        heading_texts = {re.sub(r"\W", "", u["text"]).lower() for u in page_units}
        for x0, y0, x1, y1, txt, _, btype in doc[pi].get_text("blocks"):
            txt = txt.strip()
            if btype != 0 or not txt:
                continue
            if y0 < 40 or y1 > 690:                       # running header / footer
                continue
            if re.sub(r"\W", "", txt).lower() in heading_texts:   # the heading itself
                continue
            above = [u for u in page_units if u["y0"] <= y0 + 2]
            same_col = [u for u in above if overlap(u["x0"], u["x1"], x0, x1) > 0
                        or abs(u["x0"] - x0) < 150]
            pool = same_col or above
            if pool:
                owner = max(pool, key=lambda u: u["y0"])
            else:                                          # text above first heading on page:
                earlier = [u for u in units if u["pdf_page"] < page_no]   # continues previous unit
                if not earlier:
                    continue
                owner = earlier[-1]
            owner["body"].append(clean_text(txt))
    for u in units:
        u["body"] = " ".join(u["body"])
    return units


# ---- Step B: merge small units into chunks, keep metadata ---------------------
def kind_of(u):
    if u["level"] == "song":
        return "song"
    if re.search(r"Session \d+ Assignment", u["text"]):
        return "assignment"
    return "explanation"


def make_chunk(units, session):
    kind = units[0]["kind"]
    body = " ".join(u["body"] for u in units if u["body"])
    text = "\n".join(f"{u['text']}: {u['body']}".strip(": ") if u["body"] else u["text"] for u in units)
    p0, p1 = min(u["pdf_page"] for u in units), max(u["pdf_page"] for u in units)
    return {
        "session": session["session"], "session_title": session["title"],
        "chunk_type": kind, "headings": [u["text"] for u in units],
        "pdf_page_start": p0, "pdf_page_end": p1,
        "printed_page_start": p0 - OFFSET, "printed_page_end": p1 - OFFSET,
        "page_images": [f"page_{p:03d}.png" for p in range(p0, p1 + 1)],
        "text": text, "body_chars": len(body),
        "embeddable": len(body) >= MIN_BODY_TO_EMBED,
        "has_notation": kind == "song" or len(body) < 150,   # heuristic: text can't be the whole story
    }


def merge(units, toc):
    def session_of(p):
        return next(s for s in toc if s["pdf_page"] <= p <= s["pdf_page_end"])
    chunks, buf, buf_chars, buf_session = [], [], 0, None

    def flush():
        nonlocal buf, buf_chars
        if buf:
            chunks.append(make_chunk(buf, buf_session))
        buf, buf_chars = [], 0

    for u in units:
        u["kind"] = kind_of(u)
        sess = session_of(u["pdf_page"])
        if buf and sess["session"] != buf_session["session"]:
            flush()                                        # never cross a session boundary
        if u["kind"] in ("song", "assignment"):
            flush()
            chunks.append(make_chunk([u], sess))           # standalone, whatever its size
            continue
        if buf and buf_chars + len(u["body"]) > MAX_CHARS:
            flush()
        buf.append(u); buf_chars += len(u["body"]); buf_session = sess
        if buf_chars >= MIN_CHARS:
            flush()
    flush()
    return chunks


if __name__ == "__main__":
    doc = pymupdf.open(PDF)
    heads = json.load(open("headings.json"))
    toc = json.load(open("toc.json"))
    chunks = merge(assign_text(doc, heads), toc)
    for i, c in enumerate(chunks):
        c["chunk_id"] = f"c{i:03d}"
    json.dump(chunks, open("chunks.json", "w"), indent=1)

    import statistics as st
    emb = [c for c in chunks if c["embeddable"]]
    sizes = [c["body_chars"] for c in emb]
    print(f"{len(chunks)} chunks | embeddable {len(emb)} | metadata-only {len(chunks)-len(emb)}")
    print("by type:", {t: sum(c['chunk_type'] == t for c in chunks) for t in ("explanation", "song", "assignment")})
    print(f"embeddable body chars: min {min(sizes)}, median {int(st.median(sizes))}, max {max(sizes)}")
    print("has_notation:", sum(c["has_notation"] for c in chunks))