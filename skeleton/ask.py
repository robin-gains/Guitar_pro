import re
import ollama
from embedding import embed, get_collection

CHAT_MODEL = "qwen3:4b-instruct-2507-q4_K_M"
THINKING_MODELS = {"qwen3:4b"}   # hybrid models that have a reasoning mode; others get no think switches
TOP_K = 3
NUM_CTX = 4096          # context window we request; Ollama silently truncates anything longer
NO_ANSWER_DISTANCE = 0.32   # HYPOTHESIS from a handful of questions: calibrate in Milestone 7
NOT_COVERED_MSG = ("I couldn't find that in the lesson book, so I don't want to guess. "
                   "Try rephrasing, or ask about a topic from the sessions.")

SYSTEM_PROMPT = """You are a patient guitar tutor for beginners.
Answer using ONLY the book excerpts provided in the user message.
Each excerpt starts with a label like [S1 p3]. After every fact you take from an excerpt, cite its label in square brackets, exactly as written.
If the excerpts do not contain the answer, say the book does not cover it. Never invent labels or page numbers.
Be beginner-friendly. If an excerpt describes a procedure, list every step in order, including exceptions and warnings. Otherwise keep the answer short.
Chord diagrams, tablature and music notation are NOT included in the excerpts. Never state which fret, string or finger to use unless an excerpt says so in words. If the question needs a diagram, say that the book shows it in a diagram and give the page label.
If you add general guitar knowledge that is NOT in the excerpts, put it in a final line that starts with "Beyond the book:" and do not cite it."""

LABEL_RE = re.compile(r"\[S(\d{1,2}) p(\d{1,3})(?:-(\d{1,3}))?\]")


def clean_answer(text):
    """Qwen3 may put its reasoning in the visible text, ended by a closing </think> tag.
    Students must never see it, so keep only what follows the last </think>."""
    if "</think>" in text:
        text = text.split("</think>")[-1]
    return text.strip()


def extract_filters(question):
    m = re.search(r"\bsession\s+(\d{1,2})\b", question, re.I)
    return {"session": int(m.group(1))} if m else None


def label(meta):
    s, e = meta["printed_page_start"], meta["printed_page_end"]
    return f"S{meta['session']} p{s}" if s == e else f"S{meta['session']} p{s}-{e}"


def build_context(docs, metas):
    blocks = []
    for doc, m in zip(docs, metas):
        block = f"[{label(m)}] ({m['session_title']})\n{doc}"
        if m["has_notation"]:
            block += "\n(Note: this part of the book also uses music notation or diagrams that are not included in this text.)"
        blocks.append(block)
    return "\n\n".join(blocks)


def retrieve(question, k=TOP_K):
    col = get_collection()
    r = col.query(query_embeddings=embed([question], "query"),
                  n_results=k, where=extract_filters(question))
    return r["documents"][0], r["metadatas"][0], r["distances"][0]


SEE_PAGE_MSG = ("The book teaches this with a diagram or music notation, which I can't read as text, "
                "so I won't describe it from memory. Open the page below to see it.")
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
            "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12}
SPECIFIC_RE = re.compile(r"\b(\d{1,2}(?:st|nd|rd|th)|" + "|".join(ORDINALS) + r")\s+(fret|string)s?\b", re.I)


def specifics(text):
    """Fret/string facts such as '3rd string' or 'fifth fret', normalised to (3, 'string') / (5, 'fret')."""
    found = set()
    for num, kind in SPECIFIC_RE.findall(text):
        n = ORDINALS.get(num.lower()) or int(re.sub(r"\D", "", num))
        found.add((n, kind.lower()))
    return found


def cited_indices(answer, metas):
    """Positions (in metas) of the retrieved chunks that the answer's [S# p#] labels point at."""
    idx = set()
    for m in LABEL_RE.finditer(answer):
        s, p0 = int(m.group(1)), int(m.group(2))
        p1 = int(m.group(3)) if m.group(3) else p0
        for i, meta in enumerate(metas):
            if meta["session"] == s and meta["printed_page_start"] <= p0 and p1 <= meta["printed_page_end"]:
                idx.add(i)
    return idx


def unsupported_specifics(answer, docs, metas):
    """Fret/string facts the answer states that the text it cites never states.
    Chord diagrams are drawings, so a model asked 'how do I play G?' may invent them from memory."""
    support = [docs[i] for i in sorted(cited_indices(answer, metas))] or docs
    return sorted(specifics(answer) - specifics(" ".join(support)))


# Chord fingerings exist in this book ONLY as diagrams, never in the text, so questions asking for a
# chord's shape cannot be answered from text. Recognise them and point to the page instead.
CHORD_NAME_RE = re.compile(r"\b[A-Ga-g](?:#|b)?(?:maj|min|dim|aug|sus|m)?\d{0,2}\s+chord\b")
CHORD_WORDS_RE = re.compile(r"\bchord\s+(?:shape|diagram|chart|fingering|position)s?\b|\bfinger(?:ing)?\s+(?:position|placement)s?\b", re.I)
HOW_RE = re.compile(r"\b(?:how|play|playing|finger|fingers|fingering|shape|form|make|hold|position|place|put)\b", re.I)
SEE_CHORD_MSG = ("The book shows chord shapes as diagrams, which I can't read as text, so I won't describe finger "
                 "positions from memory. Open the page below to see the diagram.")


def asks_for_chord_shape(question):
    named = any(m.group(0).lower() != "a chord" for m in CHORD_NAME_RE.finditer(question))   # not the article "a chord"
    return bool(CHORD_WORDS_RE.search(question)) or (named and bool(HOW_RE.search(question)))


def check_citations(answer, metas):
    """Does every [S# p#] label in the answer fall inside a chunk we actually retrieved?
    This proves the label EXISTS in our sources, not that the text supports the claim."""
    allowed = [(m["session"], m["printed_page_start"], m["printed_page_end"]) for m in metas]
    valid, invented = [], []
    for m in LABEL_RE.finditer(answer):
        s, p0 = int(m.group(1)), int(m.group(2))
        p1 = int(m.group(3)) if m.group(3) else p0
        ok = any(s == a and lo <= p0 and p1 <= hi for a, lo, hi in allowed)
        (valid if ok else invented).append(m.group(0))
    return {"valid": valid, "invented": invented, "uncited": not (valid or invented)}


def split_beyond(answer):
    head, sep, tail = answer.partition("Beyond the book:")
    return head.strip(), (tail.strip() if sep else None)


def answer_question(question, think=False, show_prompt=False, model=None):
    model = model or CHAT_MODEL
    has_thinking_mode = model in THINKING_MODELS
    docs, metas, dists = retrieve(question)
    sources = [{"label": label(m), "headings": m["headings"],
                "printed_pages": [m["printed_page_start"], m["printed_page_end"]],
                "pdf_pages": [m["pdf_page_start"], m["pdf_page_end"]],
                "distance": round(d, 3)} for m, d in zip(metas, dists)]

    # GATE: decided by our code, before the model is ever called
    if not dists or dists[0] > NO_ANSWER_DISTANCE:
        return {"status": "not_covered", "answer": NOT_COVERED_MSG, "beyond": None,
                "sources": sources, "citations": None, "stats": None}

    if asks_for_chord_shape(question):          # no model call needed: the answer is a picture
        return {"status": "see_page", "model": None, "answer": SEE_CHORD_MSG, "suppressed_answer": None,
                "unsupported": [], "beyond": None, "sources": sources, "citations": None, "stats": None}

    user_msg = f"Book excerpts:\n\n{build_context(docs, metas)}\n\nStudent question: {question}"
    if has_thinking_mode and not think:
        user_msg += " /no_think"        # Qwen3 soft switch: skip the reasoning phase
    if show_prompt:
        print("=== USER MESSAGE SENT TO MODEL ===\n" + user_msg + "\n==================================\n")
    kwargs = {}
    if has_thinking_mode:
        kwargs["think"] = think
    resp = ollama.chat(
        model=model,
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": user_msg}],
        keep_alive="10m",
        options={"temperature": 0.2, "num_ctx": NUM_CTX},
        **kwargs,
    )
    raw = resp.message.content
    book, beyond = split_beyond(clean_answer(raw))
    unsupported = unsupported_specifics(book, docs, metas)
    status = "see_page" if unsupported else "answered"
    return {
        "status": status, "model": model,
        "answer": SEE_PAGE_MSG if unsupported else book,
        "suppressed_answer": book if unsupported else None, "unsupported": unsupported,
        "beyond": None if unsupported else beyond, "sources": sources,
        "citations": check_citations(book, metas),
        "stats": {"seconds": round(resp.total_duration / 1e9, 1),
                  "load_s": round(resp.load_duration / 1e9, 1),
                  "prompt_s": round(resp.prompt_eval_duration / 1e9, 1),
                  "write_s": round(resp.eval_duration / 1e9, 1),
                  "prompt_tokens": resp.prompt_eval_count, "answer_tokens": resp.eval_count,
                  "reasoning_chars_removed": len(raw) - len(clean_answer(raw))},
    }


def ask(question, think=False, show_prompt=False, model=None):
    r = answer_question(question, think=think, show_prompt=show_prompt, model=model)
    print(f"[{r['status']}] {r['answer']}")
    if r["beyond"]:
        print(f"Beyond the book: {r['beyond']}")
    c = r["citations"]
    if c:
        if c["invented"]:
            print(f"!! WARNING: cited sources we did not retrieve: {c['invented']}")
        if c["uncited"]:
            print("!! WARNING: answer contains no citations")
    print("--- sources:", [(s["label"], s["distance"]) for s in r["sources"]])
    if r["stats"]:
        print("--- stats:", r["stats"])
    return r


if __name__ == "__main__":
    ask("How do I tune by ear?", show_prompt=True)