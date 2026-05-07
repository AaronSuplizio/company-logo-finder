"""
LogoLift — Streamlit app
"""

import base64
import re
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

_IS_MAC = sys.platform == "darwin"

from logo_finder import find_logos
import logo_cache

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="LogoLift",
    page_icon="🏋️",
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

    /* Hover overlay for clickable thumbnails (button is moved inside .thumb-img by JS) */
    .thumb-img button:hover {
        background: rgba(0, 0, 0, 0.07) !important;
    }

    /* Accept button — green */
    div.st-key-accept_btn button {
        background-color: #2e7d32 !important;
        border-color: #2e7d32 !important;
        color: white !important;
    }
    div.st-key-accept_btn button:hover {
        background-color: #1b5e20 !important;
        border-color: #1b5e20 !important;
    }

    /* Downvote button — red */
    div.st-key-downvote_btn button {
        background-color: #c62828 !important;
        border-color: #c62828 !important;
        color: white !important;
    }
    div.st-key-downvote_btn button:hover {
        background-color: #8e0000 !important;
        border-color: #8e0000 !important;
    }
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
    if logo.get("cached"):
        count = logo.get("accept_count", 1)
        orig = logo.get("source_orig", "")
        st.caption(
            f"**{logo['name']}** &nbsp;·&nbsp; {orig} &nbsp;·&nbsp; {logo['format'].upper()}"
            f" &nbsp;·&nbsp; 📁 from your archive &nbsp;·&nbsp; accepted {count}×"
        )
    else:
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
        is_active = (i == current_idx)
        border = "3px solid #2e7d32" if is_active else "2px solid #ddd"
        with col:
            st.markdown(
                f'<div class="thumb-img" style="background:repeating-conic-gradient(#d0d0d0 0% 25%,#f8f8f8 0% 50%) '
                f'0 0/10px 10px;border:{border};border-radius:8px;padding:6px;text-align:center;position:relative;">'
                f'<img src="{url}" style="max-height:48px;max-width:72px;object-fit:contain;" />'
                f'</div>',
                unsafe_allow_html=True,
            )
            if not is_active:
                if st.button("​", key=f"thumb_{i}", use_container_width=True):
                    st.session_state.carousel_idx = i
                    st.rerun()

    # JS: move each button element inside its .thumb-img div so clicking the
    # image triggers the button, then collapse the now-empty button wrappers.
    components.html("""
<script>
(function () {
    function patch() {
        var doc = window.parent.document;
        doc.querySelectorAll('.thumb-img').forEach(function (thumb) {
            var col = thumb.closest('[data-testid="stColumn"]') || thumb.closest('[data-testid="column"]');
            if (!col) return;
            var bw = col.querySelector('[data-testid="stButton"]');
            if (!bw) return;
            var btn = bw.querySelector('button');
            if (!btn) return;

            // Already correctly patched — button is already inside thumb.
            if (thumb.contains(btn)) return;

            thumb.style.position = 'relative';
            btn.style.cssText =
                'position:absolute;inset:0;width:100%;height:100%;' +
                'background:transparent;border:none;box-shadow:none;' +
                'cursor:pointer;color:transparent;z-index:10;border-radius:8px;';

            thumb.appendChild(btn);

            // Collapse only the button's own wrappers — stop before any element
            // that is also an ancestor of the thumbnail image (shared parent).
            var el = bw;
            while (el && el !== col) {
                if (el.contains(thumb)) break;
                el.style.height = '0';
                el.style.minHeight = '0';
                el.style.margin = '0';
                el.style.padding = '0';
                el.style.overflow = 'hidden';
                el = el.parentElement;
            }
        });
    }

    patch();
    new MutationObserver(patch).observe(
        window.parent.document.body, {childList: true, subtree: true}
    );
}());
</script>
""", height=0)


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

st.title("🏋️ LogoLift")
st.markdown("Find, preview, and download any company logo in seconds.")
st.divider()

# ── STEP 1 ────────────────────────────────────────────────────────────────────
st.subheader("Step 1 — Search")

with st.form("search_form"):
    query = st.text_input(
        "Company name, ticker symbol, or domain",
        placeholder="e.g.  Apple   |   TSLA   |   stripe.com   |   openai.com",
        key="query_input",
    )
    submitted = st.form_submit_button("Find Logos", type="primary")

if submitted and query.strip():
    q = query.strip()
    cached = logo_cache.get_logos(q)
    downvoted_urls = logo_cache.get_downvoted_urls(q)
    with st.spinner("Searching for logos…"):
        fresh = find_logos(q)
    # Order: accepted archive → normal fresh → downvoted fresh (last, but not excluded)
    cached_urls = {l["url"] for l in cached}
    fresh_new = [l for l in fresh if l["url"] not in cached_urls and l["url"] not in downvoted_urls]
    fresh_downvoted = [l for l in fresh if l["url"] not in cached_urls and l["url"] in downvoted_urls]
    logos = cached + fresh_new + fresh_downvoted
    st.session_state.logos = logos
    st.session_state.carousel_idx = 0
    st.session_state.accepted_logo = None
    st.session_state.search_done = True
    st.session_state.last_query = q
    st.session_state.save_msg = ""

# ── STEP 2 ────────────────────────────────────────────────────────────────────
if st.session_state.search_done and not st.session_state.accepted_logo:
    st.divider()

    logos = st.session_state.logos
    idx = st.session_state.carousel_idx

    if not logos:
        st.warning(
            f"No logos found for **{st.session_state.last_query}**. "
            "Try a different name or the company's domain (e.g. `stripe.com`)."
        )
    else:
        total = len(logos)
        st.subheader("Step 2 — Preview & Select")
        st.markdown(f'<p class="counter">Option {idx + 1} of {total}</p>', unsafe_allow_html=True)

        render_logo_stage(logos[idx])

        if total > 1:
            st.markdown("&nbsp;")
            render_thumbnails(logos, idx)

        st.markdown("&nbsp;")

        col_prev, col_accept, col_down, col_next = st.columns([1, 2, 2, 1])
        with col_prev:
            if st.button("← Prev", disabled=(idx == 0), use_container_width=True):
                st.session_state.carousel_idx -= 1
                st.rerun()
        with col_accept:
            if st.button("👍  Accept This Logo", key="accept_btn", use_container_width=True):
                logo_cache.save_logo(st.session_state.last_query, logos[idx])
                st.session_state.accepted_logo = logos[idx]
                st.rerun()
        with col_down:
            if st.button("👎  Downvote Logo", key="downvote_btn", use_container_width=True):
                logo_cache.downvote_logo(st.session_state.last_query, logos[idx])
                logos.pop(idx)
                st.session_state.logos = logos
                st.session_state.carousel_idx = min(idx, len(logos) - 1) if logos else 0
                st.rerun()
        with col_next:
            if st.button("Next →", disabled=(idx == total - 1), use_container_width=True):
                st.session_state.carousel_idx += 1
                st.rerun()


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

    if _IS_MAC:
        # Directory chooser — local macOS only.
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
    cols = st.columns([2, 2, 2, 1]) if _IS_MAC else st.columns([2, 2, 1])
    col_save, col_copy, col_dl, col_restart = (cols if _IS_MAC else [None] + cols)

    if _IS_MAC:
        with col_save:
            if st.button("💾  Save to Directory", type="primary", use_container_width=True):
                try:
                    path = save_logo_to_dir(logo, st.session_state.save_dir)
                    st.session_state.save_msg = f"✅ Saved: `{path}`"
                except Exception as exc:
                    st.session_state.save_msg = f"❌ Error: {exc}"
                st.rerun()

    with col_copy:
        data_url = _data_url(logo)
        components.html(f"""
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:transparent; }}
button {{
    width:100%; height:38px;
    background:white; color:rgb(49,51,63);
    border:1px solid rgba(49,51,63,0.2); border-radius:0.5rem;
    font-size:14px; font-family:"Source Sans Pro",sans-serif;
    cursor:pointer; display:flex; align-items:center; justify-content:center;
    gap:6px; transition:border-color .15s,color .15s;
}}
button:hover {{ border-color:rgb(255,75,75); color:rgb(255,75,75); }}
button.ok  {{ border-color:#2e7d32; color:#2e7d32; }}
button.err {{ border-color:#c62828; color:#c62828; }}
</style>
<button id="b" onclick="go()">📋 Copy to Clipboard</button>
<script>
var SRC = "{data_url}";
function go() {{
    var b = document.getElementById('b');
    var clip = (window.parent && window.parent.navigator && window.parent.navigator.clipboard)
               || navigator.clipboard;
    if (!clip) {{ fallback(b); return; }}

    // Resolve the blob asynchronously but call clipboard.write() NOW so iOS
    // keeps the user-gesture context alive through the promise chain.
    var blobPromise = new Promise(function(resolve, reject) {{
        var img = new Image();
        img.onload = function() {{
            var c = document.createElement('canvas');
            c.width  = img.naturalWidth  || 512;
            c.height = img.naturalHeight || 512;
            c.getContext('2d').drawImage(img, 0, 0);
            c.toBlob(function(blob) {{
                blob ? resolve(blob) : reject(new Error('toBlob failed'));
            }}, 'image/png');
        }};
        img.onerror = reject;
        img.src = SRC;
    }});

    clip.write([new ClipboardItem({{'image/png': blobPromise}})])
    .then(function() {{
        b.innerHTML = '✓ Copied!'; b.className = 'ok';
        setTimeout(function() {{ b.innerHTML = '📋 Copy to Clipboard'; b.className = ''; }}, 2000);
    }})
    .catch(function() {{ fallback(b); }});
}}
function fallback(b) {{
    var ios = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
              (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);
    b.innerHTML = ios ? '☝️ Press & hold logo to copy' : '✗ Copy failed — try downloading';
    b.className = 'err';
    setTimeout(function() {{ b.innerHTML = '📋 Copy to Clipboard'; b.className = ''; }}, 3500);
}}
</script>
""", height=40)

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
        if st.button("🔍 New Search", use_container_width=True):
            for k, v in _DEFAULTS.items():
                st.session_state[k] = v
            st.rerun()

    if _IS_MAC and st.session_state.save_msg:
        st.markdown(st.session_state.save_msg)
