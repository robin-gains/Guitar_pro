import { useState } from "react";
import "./App.css";

const API_URL = "http://127.0.0.1:8000";

// Book pages are saved as page_001.png ... named by PDF page number.
function pageUrl(pdfPage) {
  return `${API_URL}/pages/page_${String(pdfPage).padStart(3, "0")}.png`;
}

// "S7 p43" -> "Session 7 · p.43"      "S2 p8-10" -> "Session 2 · p.8-10"
function friendlyLabel(label) {
  return label.replace(/^S(\d+) p/, "Session $1 · p.");
}

// Two retrieved chunks can sit on the same page and share a label; show one chip.
function uniqueByLabel(sources) {
  const seen = new Set();
  return sources.filter((s) => {
    if (seen.has(s.label)) return false;
    seen.add(s.label);
    return true;
  });
}

// A section can span several pages: pair each PDF page (the image file) with its printed number.
function pagesOf(source) {
  const [pdfStart, pdfEnd] = source.pdf_pages;
  const [printedStart] = source.printed_pages;
  const pages = [];
  for (let p = pdfStart; p <= pdfEnd; p++) {
    pages.push({ pdf: p, printed: printedStart + (p - pdfStart) });
  }
  return pages;
}

function Message({ m }) {
  const sources = uniqueByLabel(m.sources || []);
  const cited = new Set(m.citations?.valid ?? []);
  // A "see the page" answer has no words to read, so open the page that answers the question.
  const firstCited = sources.find((s) => cited.has(`[${s.label}]`)) ?? sources[0];
  const [openLabel, setOpenLabel] = useState(m.status === "see_page" ? firstCited?.label ?? null : null);
  const open = sources.find((s) => s.label === openLabel);

  return (
    <div className={`bubble ${m.role} ${m.status || ""}`}>
      {m.text}

      {sources.length > 0 && (
        <div className="sources">
          <span className="sources-title">Book sections:</span>
          {sources.map((s) => (
            <button
              key={s.label}
              type="button"
              className={`chip ${cited.has(`[${s.label}]`) ? "cited" : ""}`}
              title={s.headings}
              aria-pressed={openLabel === s.label}
              onClick={() => setOpenLabel(openLabel === s.label ? null : s.label)}
            >
              {friendlyLabel(s.label)}
            </button>
          ))}
        </div>
      )}

      {open && (
        <div className="page-preview">
          <p className="preview-title">{open.headings}</p>
          {pagesOf(open).map((p) => (
            <img key={p.pdf} src={pageUrl(p.pdf)} alt={`Book page ${p.printed}`} loading="lazy" />
          ))}
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  async function sendQuestion(event) {
    event.preventDefault();
    const question = input.trim();
    if (!question || loading) return;

    setMessages((prev) => [...prev, { role: "student", text: question }]);
    setInput("");
    setLoading(true);

    try {
      const response = await fetch(`${API_URL}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const data = await response.json();

      if (!response.ok) {
        // 422 returns a list of problems; 500 and 503 return a plain message
        const detail = Array.isArray(data.detail)
          ? data.detail[0].msg.replace(/^Value error, /, "")
          : data.detail;
        throw new Error(detail || "Something went wrong.");
      }
      setMessages((prev) => [
        ...prev,
        {
          role: "tutor",
          text: data.answer,
          status: data.status,
          sources: data.sources,
          citations: data.citations,
        },
      ]);
    } catch (error) {
      const text =
        error instanceof TypeError
          ? "Can't reach the tutor server. Is it running? (Press F12 and check the Console for details.)"
          : error.message;
      setMessages((prev) => [...prev, { role: "tutor", text, status: "error" }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="chat">
      <h1>Guitar Tutor</h1>

      <div className="messages" aria-live="polite">
        {messages.length === 0 && (
          <p className="hint">Ask a question about your lesson book, for example “What is a half step?”</p>
        )}
        {messages.map((m, i) => (
          <Message key={i} m={m} />
        ))}
        {loading && (
          <div className="bubble tutor loading">Thinking… this can take up to 30 seconds.</div>
        )}
      </div>

      <form onSubmit={sendQuestion} className="composer">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type your question…"
          maxLength={500}
          disabled={loading}
        />
        <button type="submit" disabled={loading || !input.trim()}>
          Ask
        </button>
      </form>
    </main>
  );
}