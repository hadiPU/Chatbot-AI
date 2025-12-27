# chatbot_only.py
import streamlit as st
from datetime import datetime, timedelta
from html import escape
import os
import re
import sqlite3
import streamlit.components.v1 as components

# set_page_config harus dipanggil sebelum pemanggilan Streamlit lain
st.set_page_config(page_title="Chatbot Warung Makan Bu Yuni", layout="centered")

# ---- Try import helpers from app.py (non-UI helpers) ----
try:
    from app import (
        call_gemini_chat,        # optional helper
        list_stores,
        maps_url_for_store_row,
        get_daily_menu_from_db,
        get_product_summary_text,
    )
    APP_OK = True
except Exception as e:
    APP_OK = False
    APP_ERR = str(e)

# ---- wrapper to call Gemini (tries app.call_gemini_chat first, else google.genai) ----
def _call_gemini(prompt: str, api_key: str, system_prompt: str = "", model: str = "gemini-2.5-flash") -> str:
    # prefer app-provided helper if exists
    if 'call_gemini_chat' in globals() and callable(globals().get('call_gemini_chat')):
        try:
            return globals().get('call_gemini_chat')(prompt, api_key, system_prompt, model=model)
        except Exception as e:
            return f"Gagal memanggil helper app.call_gemini_chat: {e}"

    # fallback: try google.genai
    try:
        import google.genai as genai
        from google.genai import types
    except Exception as e:
        return f"Library google-genai tidak tersedia: {e} (pip install google-genai) atau gunakan mode lokal."

    try:
        client = genai.Client(api_key=api_key)
        cfg = types.GenerateContentConfig(system_instruction=system_prompt)
        resp = client.models.generate_content(model=model, contents=prompt, config=cfg)
        return getattr(resp, "text", str(resp))
    except Exception as e:
        return f"Gagal memanggil Gemini: {e}"

# ---- env API key and default usage flag ----
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
DEFAULT_USE_GEMINI = bool(GEMINI_API_KEY)

# ---- Modernized CSS with light theme + typing animation ----
CSS = """
<style>
:root{
  --bg-dark:#0b1220;
  --panel-dark:#0f1b26;
  --card-dark:#102731;
  --header-dark:#12313b;
  --bot-dark:#15384a;
  --user:#79e0ff;
  --muted:#9fb0c8;
  --text:#e7eef6;
  --accent:#39a7ff;
  --glass: rgba(255,255,255,0.03);

  --bg-light:#f5f7fb;
  --panel-light:#ffffff;
  --card-light:#f0f6fb;
  --header-light:#eef6ff;
  --bot-light:#e6f3fb;
  --muted-light:#6b7280;
  --text-light:#0b1220;
  --accent-light:#2b6cb0;
}

/* Base reset */
*{box-sizing:border-box}
body { margin:0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial; }

/* wrapper used to toggle theme by adding class 'chat-light' or 'chat-dark' on document.body */
.wrapper { padding:24px 0; display:flex; justify-content:center; align-items:flex-start; }

/* chat container */
.chat-wrap { width:820px; max-width:96vw; border-radius:18px; overflow:hidden; box-shadow: 0 12px 40px rgba(2,6,23,0.6); border: 1px solid rgba(255,255,255,0.02); }

/* dark theme (default) variables */
.chat-wrap.dark {
  background: linear-gradient(180deg, var(--panel-dark), #071018);
  color: var(--text);
}
.chat-wrap.dark .header { background: linear-gradient(90deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01)); border-bottom: 1px solid rgba(255,255,255,0.03); }
.chat-wrap.dark .logo { background: linear-gradient(180deg, rgba(255,255,255,0.02), rgba(0,0,0,0.08)); color:var(--text); }
.chat-wrap.dark .title, .chat-wrap.dark .sub { color:var(--text); }
.chat-wrap.dark .messages { background: linear-gradient(180deg, rgba(255,255,255,0.01), rgba(0,0,0,0.03)); }
.chat-wrap.dark .bubble.bot { background: linear-gradient(180deg, rgba(20,46,58,0.92), rgba(11,30,40,0.92)); color:var(--text); }
.chat-wrap.dark .bubble.user { background: linear-gradient(180deg, var(--user), #3bd4ff); color:#01242e; box-shadow: 0 6px 18px rgba(3,90,116,0.16); }
.chat-wrap.dark .qbtn { color:var(--text); border-color: rgba(255,255,255,0.05); }
.chat-wrap.dark .input-field { background: rgba(255,255,255,0.015); color:var(--text); border:1px solid rgba(255,255,255,0.03); }
.chat-wrap.dark .send { background: var(--accent); color:#04293e; }

/* light theme overrides */
.chat-wrap.light {
  background: linear-gradient(180deg, var(--panel-light), var(--panel-light));
  color: var(--text-light);
  border: 1px solid rgba(11,18,32,0.04);
}
.chat-wrap.light .header { background: var(--header-light); border-bottom: 1px solid rgba(11,18,32,0.04); }
.chat-wrap.light .logo { background: linear-gradient(180deg, rgba(0,0,0,0.02), rgba(0,0,0,0.01)); color:var(--text-light); }
.chat-wrap.light .title, .chat-wrap.light .sub { color:var(--text-light); }
.chat-wrap.light .messages { background: var(--card-light); }
.chat-wrap.light .bubble.bot { background: var(--bot-light); color:var(--text-light); border:1px solid rgba(11,18,32,0.03); }
.chat-wrap.light .bubble.user { background: linear-gradient(180deg, #9feeff, #62d8ff); color:#00323a; }
.chat-wrap.light .qbtn { color:var(--text-light); border-color: rgba(11,18,32,0.06); background: rgba(0,0,0,0.01); }
.chat-wrap.light .input-field { background: #ffffff; color:var(--text-light); border:1px solid rgba(11,18,32,0.06); }
.chat-wrap.light .send { background: var(--accent-light); color:#fff; }

/* common layout */
.header { display:flex; align-items:center; gap:16px; padding:18px 20px; }
.logo { width:56px; height:56px; border-radius:12px; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:15px; border:1px solid rgba(255,255,255,0.03); box-shadow: 0 6px 18px rgba(2,6,23,0.45) inset; }
.title { font-weight:800; font-size:18px; letter-spacing:0.2px; }
.sub { font-size:13px; margin-top:2px; opacity:0.95; }

/* messages area */
.content { display:flex; gap:0; flex-direction:column; }
.messages-wrap { padding:18px; }
.messages { height:520px; min-height:240px; max-height:72vh; padding:18px; border-radius:12px; display:flex; flex-direction:column; justify-content:flex-end; gap:14px; overflow-y:auto; }

/* message row */
.msg-row { display:flex; gap:12px; align-items:flex-end; width:100%; }

/* avatar */
.avatar { width:40px; height:40px; border-radius:10px; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:12px; border:1px solid rgba(255,255,255,0.03); }

/* bubbles */
.bubble {
  padding:12px 16px; border-radius:12px; max-width:78%; line-height:1.5; word-break:break-word; border:1px solid rgba(255,255,255,0.02);
}
.bubble.bot { box-shadow: 0 8px 28px rgba(2,6,23,0.55); border-top-left-radius:8px; }
.bubble.user { border-top-right-radius:8px; margin-left:auto; box-shadow: 0 6px 18px rgba(3,90,116,0.08); }

/* timestamp */
.ts { font-size:11px; color:var(--muted); margin-top:6px; }

/* quick replies */
.qrow { display:flex; gap:10px; flex-wrap:wrap; padding:14px 18px; border-top:1px solid rgba(255,255,255,0.02); background:transparent; }
.qbtn { padding:9px 14px; border-radius:999px; background:transparent; cursor:pointer; font-size:13px; transition:all .18s ease; box-shadow: 0 4px 10px rgba(2,6,23,0.12); }
.qbtn:hover { transform:translateY(-3px); }

/* input */
.input-bar { display:flex; gap:10px; padding:16px 18px; align-items:center; border-top:1px solid rgba(255,255,255,0.02); }
.input-field { flex:1; padding:12px 14px; border-radius:999px; font-size:14px; }
.send { padding:9px 16px; border-radius:999px; font-weight:700; border:none; cursor:pointer; transition: transform .12s ease; }
.send:hover { transform: translateY(-2px); }

/* status & note */
.status { padding:8px 14px; margin:8px 16px; border-radius:10px; font-size:13px; color:var(--muted); }
.note { padding:12px 16px 18px 16px; font-size:13px; color:var(--muted); }
.error { padding:10px 16px; color:#d14343; background:#ffdcdc33; border-radius:8px; margin:8px 16px; }

/* overlay (full-screen) with typing animation */
.chat-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: rgba(2,6,23,0.72);
  display:flex;
  align-items:center;
  justify-content:center;
  color: #fff;
  font-size:18px;
  font-weight:700;
  backdrop-filter: blur(6px);
  text-align:center;
  padding:20px;
}
.typing-box { display:flex; flex-direction:column; align-items:center; gap:8px; }
.typing-line { font-size:18px; font-weight:700; color: #fff; opacity:0.98; }
.dots { display:flex; gap:8px; align-items:flex-end; height:18px; }
.dots span {
  width:10px; height:10px; background: #fff; border-radius:50%; display:inline-block; transform: translateY(0);
  animation: dotUp 1s infinite ease-in-out;
  opacity:0.95;
}
.dots span:nth-child(2) { animation-delay: 0.15s; }
.dots span:nth-child(3) { animation-delay: 0.3s; }
@keyframes dotUp {
  0% { transform: translateY(0); opacity:0.6; }
  40% { transform: translateY(-8px); opacity:1; }
  80% { transform: translateY(0); opacity:0.6; }
  100% { transform: translateY(0); opacity:0.6; }
}

/* responsive */
@media (max-width:640px){
  .chat-wrap { width: 96vw; border-radius:12px; }
  .messages { height: 60vh; padding:12px; gap:10px; }
  .header { padding:12px; }
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ---- session state init ----
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [
        {"who": "bot", "text": "Halo! Saya Chatbot Warung Makan Bu Yuni. Ada yang bisa saya bantu? 😊", "ts": datetime.now().isoformat()}
    ]
if "chat_input" not in st.session_state:
    st.session_state.chat_input = ""
if "processing_lock" not in st.session_state:
    st.session_state.processing_lock = False
if "use_gemini_ui" not in st.session_state:
    st.session_state.use_gemini_ui = DEFAULT_USE_GEMINI
if "theme" not in st.session_state:
    # 'dark' or 'light'
    st.session_state.theme = "dark"

# small dedupe state
if "last_user_msg" not in st.session_state:
    st.session_state.last_user_msg = None
if "last_bot_msg" not in st.session_state:
    st.session_state.last_bot_msg = None

# ---- helper: build context for Gemini prompt (stores + product summary) ----
def _build_context_for_gemini():
    lokasi_info = ""
    prod_summary = ""
    try:
        if APP_OK:
            stores = list_stores()
            if stores:
                lines = []
                for s in stores:
                    try:
                        name = s["name"]
                        addr = s["address"] or ""
                        phone = s["phone"] or ""
                    except Exception:
                        name = s.get("name", "")
                        addr = s.get("address", "")
                        phone = s.get("phone", "")
                    url = maps_url_for_store_row(s)
                    if url:
                        lines.append(f"{name} — {addr} (Tel: {phone}) | MAPS: {url}")
                    else:
                        lines.append(f"{name} — {addr} (Tel: {phone})")
                lokasi_info = "\n".join(lines)
        try:
            if 'get_product_summary_text' in globals():
                prod_summary = get_product_summary_text(limit=12)
        except Exception:
            prod_summary = ""
    except Exception:
        pass
    return lokasi_info, prod_summary

# ---- core local logic (safe sqlite3 usage) ----
def local_logic(q: str) -> str:
    ql = q.lower().strip()

    # Harga detection (ketat: harus awalan cek harga/harga/berapa harga)
    m = None
    if ql.startswith("cek harga ") or ql.startswith("harga ") or ql.startswith("berapa harga "):
        m = re.match(r"^(?:cek\s+harga|berapa\s+harga|harga)\s+(.+)$", ql)
    if m:
        prod_query = m.group(1).strip(" ?!.")
        if not prod_query:
            return "Sebutkan nama produk setelah kata 'harga', mis. 'cek harga nasi goreng'."
        try:
            conn = sqlite3.connect("db.sqlite")
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            pat = f"%{prod_query}%"
            cur.execute("""
                SELECT p.name AS pname, pv.variant_name AS vname, pv.price AS price, pv.stock AS stock
                FROM product_variants pv
                JOIN products p ON pv.product_id = p.id
                WHERE lower(p.name) LIKE lower(?) OR lower(pv.variant_name) LIKE lower(?) OR lower(p.category) LIKE lower(?)
                ORDER BY CASE WHEN pv.stock>0 THEN 0 ELSE 1 END, pv.price ASC
                LIMIT 10
            """, (pat, pat, pat))
            rows = cur.fetchall()
            conn.close()
        except Exception as e:
            return f"Gagal membuka database: {e}"
        if not rows:
            return f"Tidak menemukan produk yang cocok untuk '{prod_query}'. Coba kata kunci lain atau periksa Admin."
        lines = [f"Hasil pencarian harga untuk '{prod_query}':"]
        for r in rows:
            name = r["pname"]
            variant = r["vname"] or "-"
            price = int(r["price"] or 0)
            stock = r["stock"] if r["stock"] is not None else "tidak diketahui"
            lines.append(f"- {name} ({variant}) → Rp {price:,}  •  Stok: {stock}")
        return "\n".join(lines)

    # Lokasi
    if any(k in ql for k in ["lokasi","alamat","di mana","cabang","store","toko terdekat","di mana toko"]):
        if APP_OK:
            try:
                stores = list_stores()
            except Exception as e:
                return f"Gagal mengakses data toko: {e}"
            if not stores:
                return "Belum ada data toko. Silakan tambahkan di Admin."
            out = ["Lokasi Toko / Cabang:"]
            for s in stores:
                try:
                    name = s["name"]
                    addr = s["address"] or ""
                    phone = s["phone"] or ""
                except Exception:
                    name = s.get("name", "")
                    addr = s.get("address", "")
                    phone = s.get("phone", "")
                url = maps_url_for_store_row(s)
                line = f"- {name}: {addr} (Tel: {phone})"
                if url:
                    line += f"  \n  👉 {url}"
                out.append(line)
            return "\n".join(out)
        return "Fungsi lokasi tidak tersedia."

    # Produk termurah
    if "termurah" in ql:
        try:
            conn = sqlite3.connect("db.sqlite")
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT p.name AS pname, pv.variant_name AS vname, pv.price AS price, pv.stock AS stock
                FROM products p JOIN product_variants pv ON p.id = pv.product_id
                WHERE pv.stock > 0
                ORDER BY pv.price ASC
                LIMIT 10
            """)
            rows = cur.fetchall()
            conn.close()
        except Exception as e:
            return f"Gagal akses DB untuk produk termurah: {e}"
        if not rows:
            return "Belum ada produk dengan stok > 0."
        lines = ["Top produk termurah (dengan stok):"]
        for r in rows[:5]:
            lines.append(f"- {r['pname']} {r['vname']} → Rp {int(r['price']):,} (stok: {r['stock']})")
        return "\n".join(lines)

    # Produk terlaris
    if "terlaris" in ql or "paling laku" in ql:
        try:
            conn = sqlite3.connect("db.sqlite")
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT p.name AS pname, pv.variant_name AS vname, pv.sold_count AS sold, pv.price AS price, pv.stock AS stock
                FROM product_variants pv JOIN products p ON pv.product_id = p.id
                WHERE pv.sold_count > 0
                ORDER BY pv.sold_count DESC
                LIMIT 10
            """)
            rows = cur.fetchall()
            conn.close()
        except Exception as e:
            return f"Gagal akses DB untuk produk terlaris: {e}"
        if not rows:
            return "Belum ada data penjualan/terlaris."
        lines = ["Top produk terlaris:"]
        for r in rows[:5]:
            lines.append(f"- {r['pname']} {r['vname']} (terjual: {r['sold']}) → Rp {int(r['price']):,} (stok: {r['stock']})")
        return "\n".join(lines)

    # Menu harian (tambah dukungan 'besok')
    if "menu" in ql:
        if APP_OK:
            try:
                offset = 1 if "besok" in ql or "besoknya" in ql else 0
                date_str = (datetime.now().date() + timedelta(days=offset)).isoformat()
                items = get_daily_menu_from_db(date_str)
            except Exception as e:
                return f"Gagal ambil menu: {e}"
            if not items:
                return f"Menu untuk {date_str} belum tersedia."
            out = [f"Menu untuk {date_str}:"]
            for it in items:
                out.append(f"- {it.get('name')} {it.get('variant_name')} → Rp{int(it.get('price',0)):,} (stok: {it.get('stock','?')})")
            return "\n".join(out)
        return "Fungsi menu tidak tersedia."

    # Greetings
    if any(g in ql for g in ["halo","hai","hello"]):
        return "Halo! Saya Chatbot Warung Taburai. Coba tanya: 'menu hari ini', 'lokasi toko', atau 'cek harga [produk]'."

    return None

# ---- function to process a message (either quick or typed) ----
def process_message(q: str):
    """
    Behaviour:
    - local-only keywords use local_logic
    - rekomendasi/saran -> Gemini if available
    - otherwise use Gemini when toggle ON, else local
    - show full-screen overlay (gelap) + typing animation when Gemini called
    """
    q_str = (q or "").strip()
    if not q_str:
        return

    # dedupe
    if st.session_state.get("last_user_msg") == q_str:
        return

    if st.session_state.get("processing_lock"):
        return
    st.session_state.processing_lock = True
    st.session_state.last_user_msg = q_str

    # append user message
    st.session_state.chat_history.append({"who": "user", "text": escape(q_str), "ts": datetime.now().isoformat()})

    ql = q_str.lower()
    force_gemini_intent = any(k in ql for k in ["rekomendasi", "sarankan", "saran"])
    local_only_keywords = ["termurah", "terlaris", "harga", "menu", "lokasi", "alamat", "stok", "cek harga"]
    force_local = any(k in ql for k in local_only_keywords)

    if force_gemini_intent and GEMINI_API_KEY:
        force_local = False

    status_placeholder = st.empty()
    bot_reply = None

    try:
        if force_local:
            status_placeholder.info("Memproses (lokal)...")
            try:
                bot_reply = local_logic(q_str)
            except Exception as e:
                bot_reply = f"Error lokal: {e}"
            status_placeholder.empty()
        else:
            use_gemini_now = False
            if force_gemini_intent and GEMINI_API_KEY:
                use_gemini_now = True
            else:
                use_gemini_now = (st.session_state.get("use_gemini_ui", False) and GEMINI_API_KEY)

            if use_gemini_now:
                # show overlay with typing animation
                overlay_ph = st.empty()
                overlay_html = """
                <div class="chat-overlay">
                  <div class="typing-box">
                    <div class="typing-line">Menghubungi Gemini... Mohon tunggu</div>
                    <div class="dots"><span></span><span></span><span></span></div>
                  </div>
                </div>
                """
                overlay_ph.markdown(overlay_html, unsafe_allow_html=True)

                lokasi_info, prod_summary = _build_context_for_gemini()
                system_prompt = (
                    "Kamu adalah asisten penjualan untuk toko online. Jawab singkat, jelas, dan akurat.\n"
                    "PENTING: Jangan sertakan alamat lengkap atau link Google Maps kecuali pengguna secara eksplisit menanyakan lokasi, arah, cara ambil, atau pengiriman."
                )
                full_system = system_prompt + ("\n\nRingkasan produk:\n" + prod_summary if prod_summary else "")
                if lokasi_info:
                    full_system += "\n\nData toko (untuk lokasi jika diminta):\n" + lokasi_info

                status_placeholder.info("Menghubungi Gemini — mohon tunggu...")
                try:
                    ans = _call_gemini(f"Pertanyaan: {q_str}\n\nJawab singkat dan gunakan data jika relevan.", GEMINI_API_KEY, full_system)
                    bot_reply = ans
                except Exception as e:
                    bot_reply = f"Gagal memanggil Gemini: {e}"
                status_placeholder.empty()

                # remove overlay
                overlay_ph.empty()
            else:
                status_placeholder.info("Memproses (lokal) - Gemini tidak aktif...")
                try:
                    bot_reply = local_logic(q_str)
                except Exception as e:
                    bot_reply = f"Error lokal: {e}"
                status_placeholder.empty()

        if not bot_reply:
            bot_reply = "Maaf, saya belum mengerti. Coba 'cek harga [produk]' atau 'menu hari ini'."

        # append bot reply (dedupe)
        if st.session_state.get("last_bot_msg") != bot_reply:
            st.session_state.chat_history.append({"who": "bot", "text": escape(bot_reply), "ts": datetime.now().isoformat()})
            st.session_state.last_bot_msg = bot_reply

    finally:
        st.session_state.chat_input = ""
        st.session_state.processing_lock = False
        try:
            status_placeholder.empty()
        except Exception:
            pass

# quick reply handler
def handle_quick(val: str):
    process_message(val)

# ---- UI build ----

# Header (title + toggles) must be placed before we apply page-level CSS override,
# so we can update st.session_state.theme immediately and then inject page styles.
logo_path = "logo.png"
if os.path.exists(logo_path):
    logo_html = f'<img src="{logo_path}" style="width:100%;height:100%;object-fit:cover;border-radius:10px;">'
else:
    logo_html = "<div style='width:100%;height:100%;display:flex;align-items:center;justify-content:center'>WBY</div>"

# header layout (title + toggles)
col1, col2 = st.columns([8,2])
with col1:
    st.markdown(f"""
    <div class="header">
      <div class="logo">{logo_html}</div>
      <div>
        <div class="title">Warung Makan Bu Yuni</div>
        <div class="sub">Online</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    # Gemini toggle
    tooltip = "Jika aktif dan GEMINI_API_KEY tersedia di environment, chatbot akan menggunakan Gemini. Matikan untuk pakai mode lokal."
    st.session_state.use_gemini_ui = st.checkbox("Gunakan Gemini", value=st.session_state.use_gemini_ui, help=tooltip)

    # Theme toggle (dark / light)
    # read current theme to set index correctly
    theme_index = 0 if st.session_state.theme == "dark" else 1
    theme_choice = st.radio("Tema", options=["dark", "light"], index=theme_index, horizontal=True)

    # ---- IMPORTANT: apply theme selection IMMEDIATELY so subsequent CSS uses current value ----
    st.session_state.theme = theme_choice

# ---- Apply page-level overrides based on theme (immediately after selection) ----
if st.session_state.theme == "light":
    st.markdown("""
    <style>
      /* 1. FORCE BACKGROUND & TEXT GLOBAL */
      .stApp {
        background-color: #f2f4f8 !important;
        color: #0b1220 !important;
      }
      
      /* 2. HEADER & TEXT ELEMENTS */
      h1, h2, h3, h4, h5, h6, p, label, .stMarkdown {
        color: #0b1220 !important;
      }

      /* 3. PERBAIKAN TOMBOL (QUICK OPTION & KIRIM) */
      /* Paksa tombol menjadi Putih dengan Border dan Teks Hitam */
      div[data-testid="stButton"] button {
        background-color: #ffffff !important;
        color: #0b1220 !important;
        border: 1px solid #d1d5db !important; /* Border abu-abu */
        box-shadow: 0 2px 4px rgba(0,0,0,0.05) !important;
      }
      /* Efek Hover tombol */
      div[data-testid="stButton"] button:hover {
        background-color: #e0e7ff !important; /* Biru muda saat hover */
        border-color: #39a7ff !important;
        color: #000000 !important;
      }
      /* Efek Klik (Active) */
      div[data-testid="stButton"] button:active {
        background-color: #c7d2fe !important;
        color: #000000 !important;
      }

      /* 4. PERBAIKAN INPUT TEXT (KOLOM KETIK) */
      /* Bagian dalam input */
      div[data-testid="stTextInput"] input {
        background-color: #ffffff !important;
        color: #0b1220 !important;
        border: 1px solid #d1d5db !important;
      }
      /* Placeholder text (teks samar 'Tulis pesan...') */
      div[data-testid="stTextInput"] input::placeholder {
        color: #6b7280 !important; /* Abu-abu gelap */
        opacity: 1 !important;
      }
      /* Label input (jika ada) */
      div[data-testid="stTextInput"] label {
        color: #0b1220 !important;
      }

      /* 5. CHAT CONTAINER & BUBBLES LIGHT */
      .chat-wrap.light {
        background: #ffffff !important;
        border: 1px solid rgba(0,0,0,0.1) !important;
      }
      .chat-wrap.light .messages {
        background: #f8fafc !important; /* Abu-abu sangat muda */
      }
      .chat-wrap.light .bubble.bot {
        background: #eaf3ff !important; /* Biru Bot Sangat Muda */
        color: #0b1220 !important;
        border: 1px solid #e2e8f0 !important;
        box-shadow: 0 2px 4px rgba(0,0,0,0.02) !important;
      }
      .chat-wrap.light .bubble.user {
        background: linear-gradient(180deg, #bae6fd, #7dd3fc) !important;
        color: #0c4a6e !important;
        border: none !important;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05) !important;
      }
      .chat-wrap.light .ts {
        color: #64748b !important;
      }
      
      /* 6. LOGO & HEADER WRAPPER */
      .chat-wrap.light .header {
        background: #ffffff !important;
        border-bottom: 1px solid #e2e8f0 !important;
      }
      .chat-wrap.light .title, .chat-wrap.light .sub {
        color: #0f172a !important;
      }
    </style>
    """, unsafe_allow_html=True)

    # Inject class for body (helper JS)
    components.html("""
    <script>
      const body = window.parent.document.body;
      body.classList.add('chat-light');
      body.classList.remove('chat-dark');
    </script>
    """, height=0, width=0)

else:
    # --- DARK THEME DEFAULT ---
    st.markdown("""
    <style>
      .stApp {
        background-color: #0b1220 !important;
        color: #e7eef6 !important;
      }
    </style>
    """, unsafe_allow_html=True)

    components.html("""
    <script>
      const body = window.parent.document.body;
      body.classList.add('chat-dark');
      body.classList.remove('chat-light');
    </script>
    """, height=0, width=0)
    
if not APP_OK:
    st.markdown(f'<div class="error">Warning: gagal mengimpor helper dari <code>app.py</code> — {APP_ERR}</div>', unsafe_allow_html=True)

# messages
st.markdown('<div class="content"><div class="messages-wrap"><div class="messages" id="messages">', unsafe_allow_html=True)
for msg in st.session_state.chat_history:
    who = msg.get("who")
    text = msg.get("text", "")
    ts = msg.get("ts", "")
    try:
        tstr = datetime.fromisoformat(ts).strftime("%H:%M")
    except Exception:
        tstr = ""
    if who == "bot":
        st.markdown(f'''
        <div class="msg-row">
          <div class="avatar" aria-hidden="true">WT</div>
          <div style="flex:1;">
            <div class="bubble bot">{text.replace(chr(10), "<br>")}</div>
            <div class="ts">{tstr}</div>
          </div>
        </div>
        ''', unsafe_allow_html=True)
    else:
        st.markdown(f'''
        <div class="msg-row" style="justify-content:flex-end;">
          <div style="max-width:78%;">
            <div class="bubble user">{text.replace(chr(10), "<br>")}</div>
            <div class="ts" style="text-align:right;">{tstr}</div>
          </div>
          <div class="avatar" aria-hidden="true" style="background:#0ea5a4;color:#012024;border-radius:10px;">U</div>
        </div>
        ''', unsafe_allow_html=True)
st.markdown('</div></div>', unsafe_allow_html=True)

# improved auto-scroll using MutationObserver; also try to restore focus to input
components.html(
    """
    <script>
    (function(){
      const container = document.getElementById("messages");
      function scrollToBottom(smooth=true){
        try{
          if(!container) return;
          if(smooth){
            container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
          } else {
            container.scrollTop = container.scrollHeight;
          }
        }catch(e){ console.warn(e); }
      }

      // initial short delay to allow Streamlit render
      setTimeout(()=>scrollToBottom(false), 80);

      // setup observer to auto-scroll when children change
      if(container){
        const obs = new MutationObserver((mutations) => {
          let added = mutations.some(m => m.addedNodes && m.addedNodes.length > 0);
          if(added){
            setTimeout(()=>scrollToBottom(true), 40);
          }
        });
        obs.observe(container, { childList: true, subtree: false });
      }

      // attempt to keep focus on the chat input (match placeholder text)
      function focusInput(){
        try{
          const inp = document.querySelector('input[placeholder^="Tulis pesan"]') || document.querySelector('input[placeholder*="cek harga"]');
          if(inp){ inp.focus(); }
        }catch(e){}
      }
      setTimeout(focusInput, 120);
      setTimeout(focusInput, 500);
    })();
    """,
    height=1,
)

# quick replies
st.markdown('<div class="qrow" role="list">', unsafe_allow_html=True)
quick_options = [
    ("Menu hari ini", "menu hari ini"),
    ("Lokasi toko", "lokasi toko"),
    ("Produk termurah", "produk termurah"),
    ("Produk terlaris", "produk terlaris"),
    ("Cek harga", "cek harga "),  # trailing space -> user is expected to fill product name
]
cols = st.columns([1,1,1])
idx = 0
for label, value in quick_options:
    col = cols[idx % 3]
    col.button(label, key=f"qr_{label}", on_click=handle_quick, args=(value,), help=label)
    idx += 1
st.markdown('</div>', unsafe_allow_html=True)

# Call Back Enter
def handle_input():
    user_text = st.session_state.get("chat_input_field", "")
    
    if user_text.strip():
        process_message(user_text)
        
        st.session_state.chat_input_field = ""

# input area UI
st.markdown('<div class="input-bar">', unsafe_allow_html=True)

# Text Input
st.text_input(
    "Pesan", 
    placeholder="Tulis pesan… (mis. 'cek harga nasi goreng')", 
    key="chat_input_field", 
    label_visibility="collapsed",
    on_change=handle_input 
)
st.button(
    "Kirim", 
    key="send_btn",
    on_click=handle_input
)

st.markdown('</div>', unsafe_allow_html=True)


# footer + close wrappers
st.markdown(f'<div class="note">Semua ini hanya demo untuk tugas akhir. Powered by Hadi ©2025. All Rights Reserved.</div>', unsafe_allow_html=True)
st.markdown('</div></div>', unsafe_allow_html=True)
