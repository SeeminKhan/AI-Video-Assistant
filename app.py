import streamlit as st
import time
import html as html_lib
import re
from datetime import datetime
from dotenv import load_dotenv
from utils.audio_processor import process_input
from core.transcriber import transcribe_all
from core.summarizer import summarize, generate_title
from core.extractor import extract_action_items, extract_key_decisions, extract_questions
from core.rag_engine import build_rag_chain, ask_question
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from io import BytesIO

load_dotenv()

# ─── Safe Markdown to HTML ────────────────────────────────────────────────────
def safe_markdown_to_html(text: str) -> str:
    if not text:
        return ""
    escaped = html_lib.escape(text)
    escaped = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', escaped)
    lines = escaped.split('\n')
    parts = []
    in_ul = False
    in_ol = False

    for line in lines:
        s = line.strip()
        if not s:
            if in_ul:
                parts.append('</ul>'); in_ul = False
            if in_ol:
                parts.append('</ol>'); in_ol = False
            continue

        bullet  = re.match(r'^[-\*\u2022]\s+(.*)', s)
        numbered = re.match(r'^(\d+)\.\s+(.*)', s)

        if bullet:
            if in_ol: parts.append('</ol>'); in_ol = False
            if not in_ul: parts.append('<ul class="md-list">'); in_ul = True
            parts.append(f'<li>{bullet.group(1)}</li>')
        elif numbered:
            if in_ul: parts.append('</ul>'); in_ul = False
            if not in_ol: parts.append('<ol class="md-list">'); in_ol = True
            parts.append(f'<li>{numbered.group(2)}</li>')
        else:
            if in_ul: parts.append('</ul>'); in_ul = False
            if in_ol: parts.append('</ol>'); in_ol = False
            parts.append(f'<p class="md-para">{s}</p>')

    if in_ul:  parts.append('</ul>')
    if in_ol:  parts.append('</ol>')
    return '\n'.join(parts)


# ─── PDF Export ───────────────────────────────────────────────────────────────
def generate_pdf_report(result_data):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=50, leftMargin=50, topMargin=50, bottomMargin=50)
    styles = getSampleStyleSheet()
    t_style = ParagraphStyle('T', parent=styles['Heading1'], fontSize=22,
                             textColor='#D4A373', spaceAfter=20, alignment=TA_CENTER,
                             fontName='Helvetica-Bold')
    h_style = ParagraphStyle('H', parent=styles['Heading2'], fontSize=14,
                             textColor='#1a1a1a', spaceAfter=10, spaceBefore=18,
                             fontName='Helvetica-Bold')
    b_style = ParagraphStyle('B', parent=styles['BodyText'], fontSize=11,
                             textColor='#2a2a2a', spaceAfter=10, fontName='Helvetica')
    m_style = ParagraphStyle('M', parent=styles['Normal'], fontSize=8,
                             textColor='#666', spaceAfter=16, alignment=TA_CENTER)
    story = [
        Paragraph("AI Video Assistant Report", t_style),
        Paragraph(f"Generated {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", m_style),
        Spacer(1, 0.2*inch),
    ]
    for label, key in [("Session Title", 'title'), ("Summary", 'summary'),
                       ("Action Items", 'action_items'), ("Key Decisions", 'key_decisions'),
                       ("Open Questions", 'open_questions')]:
        story += [Paragraph(label, h_style),
                  Paragraph(str(result_data.get(key, '')), b_style),
                  Spacer(1, 0.15*inch)]
    story += [PageBreak(), Paragraph("Full Transcript", h_style),
              Paragraph(str(result_data.get('transcript', '')), b_style)]
    doc.build(story)
    buffer.seek(0)
    return buffer


# ─── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="AI Video Assistant", layout="wide",
                   initial_sidebar_state="expanded")

# ─── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');
@import url('https://fonts.googleapis.com/icon?family=Material+Icons');

/* ── tokens ── */
:root {
    --bg:        #0B0C0F;
    --s1:        #141519;
    --s2:        #1C1E25;
    --s3:        #252830;
    --border:    rgba(212,163,89,.14);
    --borderh:   rgba(212,163,89,.32);
    --gold:      #D4A373;
    --goldb:     #E9C46A;
    --golddim:   rgba(212,163,89,.11);
    --goldglow:  rgba(212,163,89,.20);
    --text:      #F1F2F5;
    --muted:     #9BA3B0;
    --dim:       #5C6270;
    --ok:        #10B981;
    --err:       #EF4444;
    --codebg:    #0E0F12;
}

*, *::before, *::after { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body, [class*="css"], .stApp {
    font-family: 'Inter', sans-serif !important;
    background: var(--bg) !important;
    color: var(--text) !important;
}
.stApp { min-height: 100vh; }

/* ── Material Icons – must have text-transform:none or ligatures break ── */
.icon {
    font-family: 'Material Icons' !important;
    font-weight: normal !important;
    font-style: normal !important;
    font-size: 20px;
    line-height: 1;
    vertical-align: middle;
    display: inline-block;
    text-transform: none !important;
    letter-spacing: normal !important;
    word-wrap: normal !important;
    white-space: nowrap !important;
    direction: ltr !important;
    -webkit-font-feature-settings: 'liga';
    font-feature-settings: 'liga';
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: var(--s1) !important;
    border-right: 1px solid var(--border) !important;
}
[data-testid="stSidebar"] .stButton > button {
    width: 100%;
    background: linear-gradient(135deg, var(--gold) 0%, #B08040 100%) !important;
    color: #090A0C !important;
    border: none !important;
    border-radius: 10px !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 700 !important;
    font-size: 0.88rem !important;
    letter-spacing: 0.06em !important;
    text-transform: uppercase !important;
    padding: 0.75rem 1.25rem !important;
    transition: all .22s ease !important;
    box-shadow: 0 4px 16px var(--goldglow) !important;
    margin-top: 0.5rem !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 26px var(--goldglow) !important;
}

/* ── inputs ── */
.stTextInput > div > div > input {
    background: var(--s2) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    color: var(--text) !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.88rem !important;
    transition: border-color .2s, box-shadow .2s !important;
}
.stTextInput > div > div > input:focus {
    border-color: var(--gold) !important;
    box-shadow: 0 0 0 3px rgba(212,163,89,.12) !important;
    background: var(--s1) !important;
}
.stTextInput > div > div > input::placeholder { color: var(--dim) !important; }

[data-testid="stSelectbox"] > div > div {
    background: var(--s2) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    color: var(--text) !important;
}

label, [data-testid="stWidgetLabel"] {
    color: var(--muted) !important;
    font-size: 0.8rem !important;
    font-weight: 500 !important;
}

/* ── non-sidebar buttons (chat send, clear) ── */
.stButton > button:not([kind="secondary"]) {
    background: linear-gradient(135deg, var(--gold) 0%, #B08040 100%) !important;
    color: #090A0C !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 700 !important;
    letter-spacing: .04em !important;
    transition: all .22s ease !important;
    box-shadow: 0 4px 14px var(--goldglow) !important;
}
.stButton > button:not([kind="secondary"]):hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 7px 22px var(--goldglow) !important;
}
.stButton > button[kind="secondary"] {
    background: var(--s2) !important;
    border: 1px solid var(--border) !important;
    color: var(--muted) !important;
    border-radius: 10px !important;
    box-shadow: none !important;
}
.stButton > button[kind="secondary"]:hover {
    border-color: var(--gold) !important;
    color: var(--gold) !important;
    background: var(--golddim) !important;
}

[data-testid="stDownloadButton"] > button {
    background: var(--s2) !important;
    border: 1px solid var(--borderh) !important;
    color: var(--gold) !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    transition: all .2s ease !important;
}
[data-testid="stDownloadButton"] > button:hover {
    background: var(--golddim) !important;
    border-color: var(--gold) !important;
}

/* ── alerts, spinners ── */
.stAlert { background: var(--s2) !important; border: 1px solid var(--border) !important;
           border-radius: 10px !important; color: var(--text) !important; }
.stProgress > div > div > div { background: var(--gold) !important; }
.stSpinner > div { border-top-color: var(--gold) !important; }

/* ── expanders ── */
.streamlit-expanderHeader {
    background: var(--s2) !important; border: 1px solid var(--border) !important;
    border-radius: 10px !important; color: var(--text) !important; font-weight: 600 !important;
}
.streamlit-expanderContent {
    background: var(--s1) !important; border: 1px solid var(--border) !important;
    border-top: none !important; border-radius: 0 0 10px 10px !important;
}

[data-testid="stMarkdownContainer"] p { color: var(--text) !important; }

/* ── scrollbar ── */
::-webkit-scrollbar { width:6px; height:6px; }
::-webkit-scrollbar-track { background: var(--s1); border-radius:3px; }
::-webkit-scrollbar-thumb { background: var(--s3); border-radius:3px; }
::-webkit-scrollbar-thumb:hover { background: var(--gold); }

hr { border:none !important; border-top:1px solid var(--border) !important; margin:2rem 0 !important; }

/* ═══════════════ COMPONENTS ═══════════════ */

/* sidebar brand */
.sb-brand { text-align:center; padding:1.5rem 0 1.25rem; border-bottom:1px solid var(--border); margin-bottom:1.5rem; }
.sb-brand .icon { font-size:44px; color:var(--gold); display:block; margin-bottom:.55rem; }
.sb-brand h2 { margin:0 0 .2rem !important; font-size:1.25rem !important; font-weight:700 !important; color:var(--text) !important; }
.sb-brand .sub { font-size:.68rem; letter-spacing:.18em; text-transform:uppercase; color:var(--dim); }

/* chip / badge — text-transform only on label, never on icon */
.chip {
    display: inline-flex; align-items: center; gap:.3rem;
    padding: .3rem .75rem;
    border-radius: 6px;
    font-size: .72rem; font-weight: 700;
    letter-spacing: .06em;
    border: 1px solid rgba(212,163,89,.25);
    background: rgba(212,163,89,.1);
    color: #E9C46A;
}
.chip .icon { font-size:15px; text-transform:none !important; }
.chip-label { text-transform: uppercase; }
.chip-muted {
    border-color: rgba(255,255,255,.08) !important;
    background: rgba(255,255,255,.04) !important;
    color: var(--muted) !important;
}
.chip-green {
    border-color: rgba(16,185,129,.25) !important;
    background: rgba(16,185,129,.1) !important;
    color: #34D399 !important;
}

/* pipeline */
.pipe-wrap { background:var(--s1); border:1px solid var(--border); border-radius:12px; padding:.65rem; margin-top:.6rem; }
.pipe-row {
    display:flex; align-items:center; gap:.55rem;
    padding:.45rem .6rem; border-radius:8px; margin:.25rem 0;
    border:1px solid transparent; background:var(--s2);
    font-size:.81rem; color:var(--text);
    transition: all .2s ease;
}
.pipe-row.active { border-color:var(--gold); background:rgba(212,163,89,.08); }
.pipe-row.done   { border-color:var(--ok);   background:rgba(16,185,129,.07); }
.pipe-dot {
    width:20px; height:20px; border-radius:50%;
    display:flex; align-items:center; justify-content:center;
    flex-shrink:0; font-size:10px; font-weight:700;
}
.pipe-dot.pending { background:var(--s3); color:var(--dim); }
.pipe-dot.active  { background:var(--gold); color:#0B0C0F; animation:pdot 1.5s infinite; }
.pipe-dot.done    { background:var(--ok);   color:#fff; }
.pipe-row .icon   { font-size:16px; color:var(--muted); text-transform:none !important; }

@keyframes pdot {
    0%,100% { box-shadow:0 0 0 0 rgba(212,163,89,.35); }
    50%      { box-shadow:0 0 0 7px rgba(212,163,89,0); }
}

/* hero */
.hero { padding:2.75rem 0 2rem; border-bottom:1px solid var(--border); margin-bottom:2.25rem; }
.hero-h1 {
    font-size: clamp(2.2rem, 4.5vw, 3.6rem);
    font-weight: 800; line-height:1.06; letter-spacing:-.03em;
    margin:0 0 .75rem;
    background: linear-gradient(135deg, #FFFFFF 0%, var(--gold) 55%, #A07040 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}
.hero-sub { font-size:1rem; color:var(--muted); line-height:1.65; margin-bottom:1.5rem; max-width:680px; }
.hero-chips { display:flex; flex-wrap:wrap; gap:.55rem; }

/* result card */
.rc {
    background: var(--s1);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 0;
    margin-bottom: 1.25rem;
    position: relative;
    overflow: hidden;
    transition: border-color .25s, box-shadow .25s, transform .25s;
    box-shadow: 0 2px 10px rgba(0,0,0,.3);
}
.rc::before {
    content:''; position:absolute; top:0; left:0;
    width:100%; height:3px;
    background: linear-gradient(90deg, var(--gold), #8A6030);
}
.rc:hover { border-color:var(--borderh); box-shadow:0 6px 24px rgba(212,163,89,.1); transform:translateY(-2px); }
.rc-head {
    display:flex; justify-content:space-between; align-items:center;
    padding: 1rem 1.4rem .85rem;
    border-bottom: 1px solid var(--border);
}
.rc-label {
    display:flex; align-items:center; gap:.4rem;
    font-size:.75rem; font-weight:700; letter-spacing:.1em;
    text-transform:uppercase; color:var(--muted);
}
.rc-label .icon { font-size:17px; text-transform:none !important; color:var(--gold); }
.rc-body { padding: 1.25rem 1.4rem 1.5rem; }

/* title card specific */
.rc-title-text { font-size:1.5rem; font-weight:700; color:var(--text); line-height:1.3; }

/* copy button — relies on data-content, no inline JS content */
.cpbtn {
    display:inline-flex; align-items:center; gap:.3rem;
    background: var(--s2); border:1px solid var(--border); border-radius:7px;
    padding:.3rem .65rem; color:var(--muted); font-size:.76rem; font-weight:500;
    cursor:pointer; transition:all .18s ease; white-space:nowrap; font-family:'Inter',sans-serif;
}
.cpbtn .icon { font-size:15px; text-transform:none !important; }
.cpbtn:hover { background:var(--s3); color:var(--gold); border-color:var(--gold); }

/* content inside cards */
.rc-body .md-list { margin:.35rem 0 .65rem 1.1rem; padding-left:.2rem; }
.rc-body .md-list li { margin-bottom:.38rem; color:var(--text); line-height:1.65; }
.rc-body ol.md-list { list-style:decimal; }
.rc-body ul.md-list { list-style:disc; }
.rc-body .md-para { margin:0 0 .65rem; color:var(--text); line-height:1.7; }
.rc-body strong { color:var(--goldb); font-weight:600; }

/* transcript */
.trx {
    background:var(--codebg); border:1px solid var(--border); border-radius:10px;
    padding:1.25rem; font-family:'JetBrains Mono','Courier New',monospace;
    font-size:.8rem; line-height:1.8; max-height:420px; overflow-y:auto;
    color:var(--muted); white-space:pre-wrap; word-break:break-word;
}

/* chat */
.chat-box {
    background:var(--s2); border-radius:12px;
    padding:1rem 1rem .5rem; max-height:500px; overflow-y:auto;
    margin-bottom:1rem; border:1px solid var(--border);
}
.cmsg { margin-bottom:1rem; display:flex; flex-direction:column; gap:.28rem; }
.cwho {
    font-size:.67rem; font-weight:700; letter-spacing:.1em; text-transform:uppercase;
    display:flex; align-items:center; gap:.28rem;
}
.cwho.you { color:var(--gold); align-self:flex-end; }
.cwho.bot { color:var(--muted); align-self:flex-start; }
.cwho .icon { font-size:13px; text-transform:none !important; }
.cbub {
    display:inline-block; padding:.7rem 1.05rem;
    border-radius:11px; font-size:.87rem; line-height:1.6; max-width:82%;
}
.cbub.you { background:rgba(212,163,89,.12); border:1px solid rgba(212,163,89,.22); align-self:flex-end; border-bottom-right-radius:3px; }
.cbub.bot { background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.07); align-self:flex-start; border-bottom-left-radius:3px; }

.chat-empty { text-align:center; padding:2.5rem 1rem; color:var(--muted); }
.chat-empty .icon { font-size:52px; color:var(--dim); display:block; margin-bottom:.7rem; text-transform:none !important; }

/* empty state */
.empty-state { display:flex; flex-direction:column; align-items:center; justify-content:center; padding:5rem 2rem; text-align:center; }
.empty-state .icon { font-size:70px; color:var(--gold); opacity:.6; display:block; margin-bottom:1.25rem; text-transform:none !important; }
.empty-h { font-size:1.6rem; font-weight:700; color:var(--text); margin-bottom:.6rem; }
.empty-p { color:var(--muted); font-size:.92rem; max-width:460px; line-height:1.7; }

/* insight cards: make sure body scrolls nicely */
.insight-body { min-height: 200px; }
</style>

<script>
// Copy button uses data-content attribute to avoid any escaping issue
document.addEventListener('click', function(e) {
    var btn = e.target.closest('.cpbtn');
    if (!btn) return;
    var slot = document.getElementById(btn.dataset.slot);
    if (!slot) return;
    var text = slot.textContent;
    navigator.clipboard.writeText(text).then(function() {
        var orig = btn.innerHTML;
        btn.innerHTML = '<span class="icon">check</span> Copied';
        btn.style.color = '#10B981';
        btn.style.borderColor = '#10B981';
        setTimeout(function() { btn.innerHTML = orig; btn.style.color=''; btn.style.borderColor=''; }, 2200);
    });
});
</script>
""", unsafe_allow_html=True)

# ─── Session State ────────────────────────────────────────────────────────────
for _k, _v in {"result": None, "chat_history": [], "processing": False,
                "pipeline_done": False, "pipeline_steps": {}}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _status(key: str) -> str:
    s = st.session_state.pipeline_steps.get(key, "pending")
    return s if s in ("active", "done") else "pending"


def render_step(label: str, key: str, icon: str):
    s = _status(key)
    dot = "●" if s == "active" else ("✓" if s == "done" else "○")
    st.markdown(
        f'<div class="pipe-row {s}">'
        f'<div class="pipe-dot {s}">{dot}</div>'
        f'<span class="icon">{icon}</span>'
        f'<span>{label}</span>'
        f'</div>',
        unsafe_allow_html=True
    )


def copy_slot(slot_id: str, raw_text: str) -> str:
    """Hidden slot that stores raw text; copy button reads from it."""
    safe_content = html_lib.escape(raw_text)
    return (
        f'<span id="{slot_id}" style="display:none">{safe_content}</span>'
        f'<button class="cpbtn" data-slot="{slot_id}">'
        f'<span class="icon">content_copy</span> Copy'
        f'</button>'
    )


def render_card(icon: str, label: str, body_html: str, slot_id: str, raw_text: str,
                extra_cls: str = ""):
    btn_html = copy_slot(slot_id, raw_text)
    st.markdown(
        f'<div class="rc">'
        f'<div class="rc-head">'
        f'<div class="rc-label"><span class="icon">{icon}</span>{label}</div>'
        f'{btn_html}'
        f'</div>'
        f'<div class="rc-body {extra_cls}">{body_html}</div>'
        f'</div>',
        unsafe_allow_html=True
    )


def chip(icon: str, label: str, cls: str = "") -> str:
    return (
        f'<span class="chip {cls}">'
        f'<span class="icon">{icon}</span>'
        f'<span class="chip-label">{label}</span>'
        f'</span>'
    )


# ─── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        '<div class="sb-brand">'
        '<span class="icon">movie</span>'
        '<h2>AI Video Assistant</h2>'
        '<span class="sub">Meeting Intelligence</span>'
        '</div>',
        unsafe_allow_html=True
    )

    st.markdown(chip("input", "Source"), unsafe_allow_html=True)
    source = st.text_input(
        "YouTube URL or File Path",
        placeholder="https://youtube.com/watch?v=...",
        label_visibility="visible"
    )
    language = st.selectbox("Transcription Language", ["english", "hinglish"], index=0)
    run_btn = st.button("Analyze", use_container_width=True)

    if st.session_state.pipeline_done:
        st.markdown('<div style="height:.5rem"></div>', unsafe_allow_html=True)
        st.markdown(chip("check_circle", "Pipeline", "chip-green"), unsafe_allow_html=True)
        st.markdown('<div class="pipe-wrap">', unsafe_allow_html=True)
        for sk, si, sl in [
            ("audio",      "graphic_eq",   "Audio Processing"),
            ("transcript", "mic",          "Transcription"),
            ("title",      "title",        "Title Generation"),
            ("summary",    "summarize",    "Summarization"),
            ("extract",    "manage_search","Extraction"),
            ("rag",        "hub",          "RAG Engine"),
        ]:
            render_step(sl, sk, si)
        st.markdown('</div>', unsafe_allow_html=True)


# ─── Hero ─────────────────────────────────────────────────────────────────────
chips_html = (
    chip("mic", "Transcribe") + " " +
    chip("summarize", "Summarize", "chip-muted") + " " +
    chip("manage_search", "Extract", "chip-muted") + " " +
    chip("chat", "Chat", "chip-muted") + " " +
    chip("picture_as_pdf", "Export PDF", "chip-muted")
)
st.markdown(
    f'<div class="hero">'
    f'<h1 class="hero-h1">AI Video Assistant</h1>'
    f'<p class="hero-sub">Transform any meeting or video into structured intelligence — '
    f'auto-transcription, executive summaries, action items, key decisions, and an interactive Q&amp;A chat.</p>'
    f'<div class="hero-chips">{chips_html}</div>'
    f'</div>',
    unsafe_allow_html=True
)

# ─── Pipeline ─────────────────────────────────────────────────────────────────
if run_btn:
    if not source.strip():
        st.error("Please enter a YouTube URL or a local file path.")
    else:
        st.session_state.update(pipeline_done=False, result=None,
                                chat_history=[], pipeline_steps={})
        ph = st.empty()

        def _set(k, v): st.session_state.pipeline_steps[k] = v

        try:
            with ph.container():
                st.info("Processing — this may take a few minutes.")

            _set("audio", "active"); chunks = process_input(source);          _set("audio", "done")
            _set("transcript", "active"); transcript = transcribe_all(chunks, language); _set("transcript", "done")
            _set("title", "active"); title = generate_title(transcript);       _set("title", "done")
            _set("summary", "active"); summary = summarize(transcript);        _set("summary", "done")
            _set("extract", "active")
            action_items = extract_action_items(transcript)
            decisions    = extract_key_decisions(transcript)
            questions    = extract_questions(transcript)
            _set("extract", "done")
            _set("rag", "active"); rag_chain = build_rag_chain(transcript);   _set("rag", "done")

            st.session_state.result = dict(
                title=title, transcript=transcript, summary=summary,
                action_items=action_items, key_decisions=decisions,
                open_questions=questions, rag_chain=rag_chain,
            )
            st.session_state.pipeline_done = True
            ph.success("Analysis complete. Scroll down for results.")
            time.sleep(0.8); ph.empty(); st.rerun()

        except Exception as exc:
            for k in ["audio", "transcript", "title", "summary", "extract", "rag"]:
                if st.session_state.pipeline_steps.get(k) == "active":
                    st.session_state.pipeline_steps[k] = "pending"
            ph.error(f"Error: {exc}")


# ─── Results ──────────────────────────────────────────────────────────────────
if st.session_state.result:
    r = st.session_state.result

    # Export bar
    _, dl_col = st.columns([5, 1])
    with dl_col:
        pdf_buf = generate_pdf_report(r)
        st.download_button("Export PDF", data=pdf_buf,
                           file_name=f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                           mime="application/pdf", use_container_width=True)

    st.markdown('<div style="height:1rem"></div>', unsafe_allow_html=True)

    # ── Session title ──────────────────────────────────────────────────────
    title_safe = html_lib.escape(r["title"])
    slot_title = copy_slot("slot-title", r["title"])
    st.markdown(
        f'<div class="rc">'
        f'<div class="rc-head">'
        f'<div class="rc-label"><span class="icon">label</span>Session Title</div>'
        f'{slot_title}'
        f'</div>'
        f'<div class="rc-body"><div class="rc-title-text">{title_safe}</div></div>'
        f'</div>',
        unsafe_allow_html=True
    )

    # ── Summary (full width) ───────────────────────────────────────────────
    render_card(
        icon="summarize", label="Executive Summary",
        body_html=safe_markdown_to_html(r["summary"]),
        slot_id="slot-summary", raw_text=r["summary"]
    )

    # ── Transcript expander ────────────────────────────────────────────────
    with st.expander("View Full Transcript", expanded=False):
        trx_safe = html_lib.escape(r["transcript"])
        st.markdown(f'<div class="trx">{trx_safe}</div>', unsafe_allow_html=True)
        st.markdown(copy_slot("slot-transcript", r["transcript"]), unsafe_allow_html=True)

    st.markdown('<div style="height:.75rem"></div>', unsafe_allow_html=True)

    # ── Three insight columns ──────────────────────────────────────────────
    st.markdown(
        '<p style="font-size:.78rem;font-weight:700;letter-spacing:.1em;'
        'text-transform:uppercase;color:var(--muted);margin-bottom:.75rem">Key Insights</p>',
        unsafe_allow_html=True
    )
    c1, c2, c3 = st.columns(3, gap="medium")
    with c1:
        render_card("check_box", "Action Items",
                    safe_markdown_to_html(r["action_items"]), "slot-actions",
                    r["action_items"], "insight-body")
    with c2:
        render_card("gavel", "Key Decisions",
                    safe_markdown_to_html(r["key_decisions"]), "slot-decisions",
                    r["key_decisions"], "insight-body")
    with c3:
        render_card("help_outline", "Open Questions",
                    safe_markdown_to_html(r["open_questions"]), "slot-questions",
                    r["open_questions"], "insight-body")

    st.markdown("---")

    # ── Chat ──────────────────────────────────────────────────────────────
    st.markdown(
        '<div style="display:flex;align-items:center;gap:.6rem;margin-bottom:1.25rem">'
        '<span class="icon" style="font-size:26px;color:var(--gold)">chat</span>'
        '<h2 style="margin:0;font-size:1.3rem;font-weight:700;letter-spacing:-.02em">'
        'Chat with Your Meeting</h2>'
        '</div>',
        unsafe_allow_html=True
    )

    if st.session_state.chat_history:
        st.markdown('<div class="chat-box">', unsafe_allow_html=True)
        for msg in st.session_state.chat_history:
            cs = html_lib.escape(msg["content"])
            if msg["role"] == "user":
                st.markdown(
                    f'<div class="cmsg" style="align-items:flex-end">'
                    f'<span class="cwho you"><span class="icon">person</span>You</span>'
                    f'<div class="cbub you">{cs}</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    f'<div class="cmsg" style="align-items:flex-start">'
                    f'<span class="cwho bot"><span class="icon">smart_toy</span>Assistant</span>'
                    f'<div class="cbub bot">{cs}</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.markdown(
            '<div class="chat-empty">'
            '<span class="icon">forum</span>'
            '<p style="margin:.5rem 0 .3rem;font-size:.93rem">Ask anything about your meeting</p>'
            '<p style="margin:0;font-size:.78rem;color:var(--dim)">'
            'Try: "What were the main action items?" or "Who is responsible for X?"</p>'
            '</div>',
            unsafe_allow_html=True
        )

    cin, btn_c = st.columns([6, 1], gap="small")
    with cin:
        user_q = st.text_input("Question", placeholder="Ask about the meeting...",
                               label_visibility="collapsed", key="chat_input")
    with btn_c:
        send = st.button("Send", use_container_width=True, key="send_btn")

    if send and user_q.strip():
        with st.spinner("Thinking..."):
            ans = ask_question(r["rag_chain"], user_q.strip())
        st.session_state.chat_history.append({"role": "user", "content": user_q.strip()})
        st.session_state.chat_history.append({"role": "assistant", "content": ans})
        st.rerun()

    if st.session_state.chat_history:
        cc1, _, _ = st.columns([1, 3, 2])
        with cc1:
            if st.button("Clear Chat", type="secondary", use_container_width=True):
                st.session_state.chat_history = []
                st.rerun()

else:
    # ── Empty state ──────────────────────────────────────────────────────
    st.markdown(
        '<div class="empty-state">'
        '<span class="icon">video_library</span>'
        '<div class="empty-h">Ready to Analyze Your Content</div>'
        '<div class="empty-p">'
        'Paste a YouTube URL or local file path in the sidebar, choose the transcription language, '
        'and click <strong style="color:var(--gold)">Analyze</strong> to begin. '
        'The AI pipeline will transcribe, summarize, and extract actionable insights automatically.'
        '</div>'
        '</div>',
        unsafe_allow_html=True
    )
