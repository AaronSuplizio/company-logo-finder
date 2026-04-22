"""
Company Logo Finder — Streamlit app
"""

import base64
import re
from pathlib import Path

import streamlit as st

from logo_finder import find_logos

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Company Logo Finder",
    page_icon="🔍",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    /* Checkerboard transparency background */
    .logo-stage {
        background:
            repeating-conic-gradient(#d0d0d0 0% 25%, #f8f8f8 0% 50%)
            0 0 / 18px 18px;
        border: 1px solid #ccc;
        border-radius: 12px;
        padding: 32px 24px;
        text-align: center;
        min-height: 200px;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .thumb-active {
        border: 3px solid #2e7d32 !important;
        border-radius: 8px;
    }
    .thumb-inactive {
        border: 2px solid #ddd !important;
        border-radius: 8px;
    }
    .counter {
        text-align: center;
        color: #777;
        font-size: 0.85rem;
        margin-bottom: 6px;
    }
    h2 { margin-top: 0.5rem !important; }
    div[data-testid="stHorizontalBlock"] { align-items: center; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _data_url(logo: dict) -> str:
    b64 = base64.b64encode(logo["content"]).decode()
    mime = "image/svg+xml" if logo["format"] == "svg" else "image/png"
    return f"data:{mime};base64,{b64}"


def render_logo_stage(logo: dict):
    url = _data_url(logo)
    st.markdown(
        f'<div class="logo-stage">'
        f'<img src="{url}" style="max-height:180px;max-width:440px;object-fit:contain;" />'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"**{logo['name']}** &nbsp;·&nbsp; {logo['source']} &nbsp;·&nbsp; {logo['format'].upper()}"
    )


def render_thumbnails(logos: list[dict], current_idx: int):
    n = min(len(logos), 6)
    cols = st.columns(n)
    for i, col in enumerate(cols):
        if i >= len(logos):
            break
        url = _data_url(logos[i])
        border = "3px solid #2e7d32" if i == current_idx else "2px solid #ddd"
        with col:
            st.markdown(
                f'<div style="background:repeating-conic-gradient(#d0d0d0 0% 25%,#f8f8f8 0% 50%) '
                f'0 0/10px 10px;border:{border};border-radius:8px;padding:6px;text-align:center;">'
                f'<img src="{url}" style="max-height:48px;max-width:72px;object-fit:contain;" />'
                f'</div>',
                unsafe_allow_html=True,
            )


def open_dir_picker() -> "str | None":
    import subprocess
    try:
        result = subprocess.run(
            ["osascript", "-e",
             'POSIX path of (choose folder with prompt "Choose Download Directory")'],
            capture_output=True, text=True, timeout=60
        )
        path = result.stdout.strip()
        return path if result.returncode == 0 and path else None
    except Exception:
        return None


def _safe_filename(name: str, ext: str) -> str:
    stem = re.sub(r"[^\w\-]", "_", name.split("(")[0].strip())
    stem = re.sub(r"_+", "_", stem).strip("_") or "logo"
    return f"{stem}_logo.{ext}"


def save_logo_to_dir(logo: dict, directory: str) -> str:
    filename = _safe_filename(logo["name"], logo["format"])
    dest = Path(directory) / filename
    dest.write_bytes(logo["content"])
    return str(dest)


# ── Session state defaults ────────────────────────────────────────────────────

_DEFAULTS: dict = {
    "logos": [],
    "carousel_idx": 0,
    "accepted_logo": None,
    "show_website_input": False,
    "search_done": False,
    "last_query": "",
    "save_dir": str(Path.home() / "Downloads"),
    "save_msg": "",
    "dir_version": 0,
}

for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ── App ───────────────────────────────────────────────────────────────────────

st.title("🔍 Company Logo Finder")
st.markdown("Search for a company and download its vector or transparent logo.")
st.divider()

# ── STEP 1 ────────────────────────────────────────────────────────────────────
st.subheader("Step 1 — Search")

query = st.text_input(
    "Company name, ticker symbol, or domain",
    placeholder="e.g.  Apple   |   TSLA   |   stripe.com   |   OpenAI",
    key="query_input",
)

if st.button("Find Logos", type="primary", disabled=not query.strip()):
    with st.spinner("Searching for logos…"):
        logos = find_logos(query.strip())
    st.session_state.logos = logos
    st.session_state.carousel_idx = 0
    st.session_state.accepted_logo = None
    st.session_state.search_done = True
    st.session_state.last_query = query.strip()
    st.session_state.show_website_input = not logos
    st.session_state.save_msg = ""

# ── STEP 2 ────────────────────────────────────────────────────────────────────
if st.session_state.search_done and not st.session_state.accepted_logo:
    st.divider()

    logos = st.session_state.logos
    idx = st.session_state.carousel_idx

    if logos:
        total = len(logos)
        st.subheader("Step 2 — Preview & Select")
        st.markdown(f'<p class="counter">Option {idx + 1} of {total}</p>', unsafe_allow_html=True)

        render_logo_stage(logos[idx])

        if total > 1:
            st.markdown("&nbsp;")
            render_thumbnails(logos, idx)

        st.markdown("&nbsp;")

        col_prev, col_accept, col_next = st.columns([1, 2, 1])
        with col_prev:
            if st.button("← Prev", disabled=(idx == 0), use_container_width=True):
                st.session_state.carousel_idx -= 1
                st.rerun()
        with col_accept:
            if st.button("✓  Accept This Logo", type="primary", use_container_width=True):
                st.session_state.accepted_logo = logos[idx]
                st.rerun()
        with col_next:
            if st.button("Next →", disabled=(idx == total - 1), use_container_width=True):
                st.session_state.carousel_idx += 1
                st.rerun()

        st.markdown("&nbsp;")
        if st.button("None of these — search by website URL"):
            st.session_state.show_website_input = True
            st.rerun()

    # Website-URL fallback
    if not logos or st.session_state.show_website_input:
        if not logos:
            st.warning(f"No logos found for **{st.session_state.last_query}**.")

        st.subheader("Search by Website URL")
        st.markdown("Enter the company's official website so we can find the logo directly:")

        website = st.text_input(
            "Website URL", placeholder="https://www.company.com", key="website_input"
        )

        if st.button("Search Website", type="primary", disabled=not website.strip()):
            with st.spinner("Scanning website for logos…"):
                new_logos = find_logos(
                    st.session_state.last_query, website_url=website.strip()
                )
            if new_logos:
                st.session_state.logos = new_logos
                st.session_state.carousel_idx = 0
                st.session_state.show_website_input = False
                st.rerun()
            else:
                st.error("No logos found at that URL. Try the company's main domain.")

# ── STEP 3 ────────────────────────────────────────────────────────────────────
if st.session_state.accepted_logo:
    logo = st.session_state.accepted_logo
    st.divider()

    st.subheader("Step 3 — Download")
    st.success(
        f"Accepted: **{logo['name']}** · {logo['format'].upper()} · {logo['source']}"
    )

    render_logo_stage(logo)
    st.markdown("&nbsp;")

    # Directory chooser.
    # dir_version increments whenever Browse picks a new path, giving the text
    # input a brand-new key so Streamlit always honors value= on that render.
    dir_key = f"dir_input_{st.session_state.dir_version}"

    def _sync_dir():
        st.session_state.save_dir = st.session_state[dir_key]

    col_dir, col_browse = st.columns([5, 1])
    with col_dir:
        st.text_input(
            "Save directory",
            value=st.session_state.save_dir,
            key=dir_key,
            on_change=_sync_dir,
        )
    with col_browse:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Browse…"):
            chosen = open_dir_picker()
            if chosen:
                st.session_state.save_dir = chosen
                st.session_state.dir_version += 1  # new key → fresh widget
                st.rerun()

    st.markdown("&nbsp;")
    col_save, col_dl, col_restart = st.columns([2, 2, 1])

    with col_save:
        if st.button("💾  Save to Directory", type="primary", use_container_width=True):
            try:
                path = save_logo_to_dir(logo, st.session_state.save_dir)
                st.session_state.save_msg = f"✅ Saved: `{path}`"
            except Exception as exc:
                st.session_state.save_msg = f"❌ Error: {exc}"
            st.rerun()

    with col_dl:
        filename = _safe_filename(logo["name"], logo["format"])
        mime = "image/svg+xml" if logo["format"] == "svg" else "image/png"
        st.download_button(
            "⬇️  Download via Browser",
            data=logo["content"],
            file_name=filename,
            mime=mime,
            use_container_width=True,
        )

    with col_restart:
        if st.button("🔄 Restart", use_container_width=True):
            for k, v in _DEFAULTS.items():
                st.session_state[k] = v
            st.rerun()

    if st.session_state.save_msg:
        st.markdown(st.session_state.save_msg)
