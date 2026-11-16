
import logging
from pathlib import Path
from typing import Literal, Optional

import ollama
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from ask import answer_question
from embedding import get_collection

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("guitar_tutor")
app = FastAPI(title="Guitar Tutor API")

# Browsers block a page on one origin (the React dev server) from calling an API on another
# unless the API says so. List the exact origins we trust; never "*" for anything real.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# Serve the rendered book pages (page_images/page_046.png -> http://127.0.0.1:8000/pages/page_046.png).
# Anchored to this file's location, not the terminal's working folder.
PAGE_DIR = Path(__file__).resolve().parent.parent / "page_images"
app.mount("/pages", StaticFiles(directory=PAGE_DIR), name="pages")

# ---------- request / response shapes (also become the docs at /docs) ----------
class AskRequest(BaseModel):
    question: str = Field(..., max_length=500)

    @field_validator("question")
    @classmethod
    def not_too_short(cls, v):
        v = v.strip()
        if len(v) < 3:
            raise ValueError("question must be at least 3 characters")
        return v


class Source(BaseModel):
    label: str
    headings: str
    printed_pages: list[int]
    pdf_pages: list[int]
    distance: float


class CitationCheck(BaseModel):
    valid: list[str]
    invented: list[str]
    uncited: bool


class AskResponse(BaseModel):
    status: Literal["answered", "not_covered", "see_page"]
    answer: str
    beyond: Optional[str] = None
    model: Optional[str] = None
    sources: list[Source]
    citations: Optional[CitationCheck] = None
    stats: Optional[dict] = None


# ---------- endpoints ----------
@app.get("/health")
def health():
    n = get_collection().count()
    return {"status": "ok" if n > 0 else "empty_index", "chunks_indexed": n}


# plain `def` (not `async def`): answer_question blocks for many seconds, and FastAPI
# runs plain-def endpoints in a worker thread so the server stays responsive.
@app.post("/ask", response_model=AskResponse)
def ask_endpoint(req: AskRequest):
    try:
        result = answer_question(req.question)
        if result["status"] == "see_page":
            # the model described fret/string facts the cited text never states; students see a page pointer instead
            log.info("see_page question=%r unsupported=%s suppressed=%r",
                     req.question, result.get("unsupported"), result.get("suppressed_answer"))
        return result
    except (ConnectionError, ollama.ResponseError):
        log.exception("Ollama unavailable or model error")
        raise HTTPException(status_code=503,
                            detail="The tutor's language model isn't available right now. Please try again in a moment.")
    except Exception:
        log.exception("Unexpected error while answering")
        raise HTTPException(status_code=500,
                            detail="Something went wrong while answering. Please try again.")