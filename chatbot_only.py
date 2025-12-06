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
    import traceback, time

    # Prefer helper dari app.py jika ada
    if 'call_gemini_chat' in globals() and callable(globals().get('call_gemini_chat')):
        try:
            return globals().get('call_gemini_chat')(prompt, api_key, system_prompt, model=model)
        except Exception as e:
            print("ERROR call_gemini_chat:", e)
            print(traceback.format_exc())

    # fallback ke google-genai
    try:
        import google.genai as genai
        from google.genai import types
    except Exception as e:
        print("google-genai tidak ditemukan:", e)
        return "Library google-genai tidak ditemukan di server Docker."

    try:
        client = genai.Client(api_key=api_key)
        cfg = types.GenerateContentConfig(system_instruction=system_prompt)

        start = time.time()
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=cfg
        )
        print(f"[Gemini] sukses dalam {time.time() - start:.2f}s")

        return getattr(resp, "text", str(resp))

    except Exception as e:
        print("ERROR Gemini API:", e)
        print(traceback.format_exc())
        return f"Gagal menghubungi Gemini: {e}"


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

  --bg-light:#f5f7fb;
  --panel-light:#ffffff;
  --card-light:#f0f6fb;
  --header-light:#eef6ff;
  --bot-light:#e6f3fb;
  --muted-light:#6b7280;
  --text-light:#0b1220;
  --accent-light:#2b6cb0;
}

*{box-sizing:border-box}
body { margin:0; font-family: Inter, ui-sans-serif, system-ui; }

.wrapper { padding:24px 0; display:flex; justify-content:center; }

.chat-wrap { width:820px; max-width:96vw; border-radius:18px; overflow:hidden; }

.chat-wrap.dark { background: linear-gradient(180deg, var(--panel-dark), #071018); color: var(--text); }
.chat-wrap.light { background: var(--panel-light); color: var(--text-light); }

.header { display:flex; align-items:center; gap:16px; padding:18px 20px; }
.logo { width:56px; height:56px; border-radius:12px; display:flex; align-items:center; justify-content:center; font-weight:800; }

.messages-wrap { padding:18px; }
.messages { height:520px; overflow-y:auto; display:flex; flex-direction:column; gap:14px; }

.bubble { padding:12px 16px; border-radius:12px; max-width:78%; line-height:1.5; }
.bubble.bot { background: var(--bot-dark); }
.bubble.user { background: var(--user); color:#01242e; margin-left:auto; }

.ts { font-size:11px; color:var(--muted); margin-top:6px; }

.qrow { display:flex; gap:10px; padding:12px; flex-wrap:wrap; }
.qbtn { padding:9px 14px; border-radius:999px; cursor:pointer; font-size:13px; }

.input-bar { display:flex; gap:10px; padding:16px; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ---- session state initialization ----
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [{
        "who": "bot",
        "text": "Halo! Saya Chatbot Warung Makan Bu Yuni. Ada yang bisa saya bantu? 😊",
        "ts": datetime.now().isoformat()
    }]

if "chat_input" not in st.session_state:
    st.session_state.chat_input = ""

if "processing_lock" not in st.session_state:
    st.session_state.processing_lock = False

if "use_gemini_ui" not in st.session_state:
    st.session_state.use_gemini_ui = DEFAULT_USE_GEMINI

if "theme" not in st.session_state:
    st.session_state.theme = "dark"

if "last_user_msg" not in st.session_state:
    st.session_state.last_user_msg = None

if "last_bot_msg" not in st.session_state:
    st.session_state.last_bot_msg = None


# ---- context builder for Gemini ----
def _build_context_for_gemini():
    lokasi_info = ""
    prod_summary = ""
    try:
        if APP_OK:
            stores = list_stores()
            if stores:
                lokasi_info = "\n".join([
                    f"{s.get('name','')} — {s.get('address','')} (Tel: {s.get('phone','')})"
                    for s in stores
                ])
        if 'get_product_summary_text' in globals():
            prod_summary = get_product_summary_text(limit=12)
    except:
        pass
    return lokasi_info, prod_summary
# ---- core local logic ----
def local_logic(q: str) -> str:
    ql = q.lower().strip()

    # Harga detection
    m = None
    if ql.startswith("cek harga ") or ql.startswith("harga ") or ql.startswith("berapa harga "):
        import sqlite3
        try:
            prod_query = ql.split(" ", 2)[-1]
        except:
            return "Format pencarian harga tidak valid."

        try:
            conn = sqlite3.connect("db.sqlite")
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            pat = f"%{prod_query}%"
            cur.execute("""
                SELECT p.name AS pname, pv.variant_name AS vname, pv.price AS price, pv.stock AS stock
                FROM product_variants pv
                JOIN products p ON pv.product_id = p.id
                WHERE lower(p.name) LIKE lower(?)
                   OR lower(pv.variant_name) LIKE lower(?)
                   OR lower(p.category) LIKE lower(?)
                ORDER BY pv.price ASC
                LIMIT 10
            """, (pat, pat, pat))
            rows = cur.fetchall()
            conn.close()
        except Exception as e:
            return f"Gagal akses database: {e}"

        if not rows:
            return f"Tidak menemukan produk untuk '{prod_query}'."

        out = [f"Hasil pencarian harga untuk '{prod_query}':"]
        for r in rows:
            out.append(f"- {r['pname']} ({r['vname']}) → Rp {int(r['price']):,}")
        return "\n".join(out)

    # Lokasi toko
    if any(k in ql for k in ["lokasi", "alamat", "di mana", "cabang", "store"]):
        if not APP_OK:
            return "Fitur lokasi tidak tersedia."

        try:
            stores = list_stores()
        except Exception as e:
            return f"Gagal mengambil data lokasi: {e}"

        if not stores:
            return "Belum ada data toko."

        out = ["Lokasi toko:"]
        for s in stores:
            name = s.get("name", "")
            addr = s.get("address", "")
            phone = s.get("phone", "")
            url = maps_url_for_store_row(s)
            line = f"- {name}: {addr} (Tel: {phone})"
            if url:
                line += f"\n  👉 {url}"
            out.append(line)
        return "\n".join(out)

    # Produk termurah
    if "termurah" in ql:
        try:
            conn = sqlite3.connect("db.sqlite")
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT p.name AS pname, pv.variant_name AS vname, pv.price AS price
                FROM product_variants pv
                JOIN products p ON pv.product_id = p.id
                WHERE pv.stock > 0
                ORDER BY pv.price ASC
                LIMIT 5
            """)
            rows = cur.fetchall()
            conn.close()
        except Exception as e:
            return f"Gagal akses DB: {e}"

        if not rows:
            return "Belum ada produk dengan stok."

        return "\n".join([
            "Top produk termurah:"
        ] + [
            f"- {r['pname']} {r['vname']} → Rp {int(r['price']):,}"
            for r in rows
        ])

    # Produk terlaris
    if "terlaris" in ql or "paling laku" in ql:
        try:
            conn = sqlite3.connect("db.sqlite")
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT p.name AS pname, pv.variant_name AS vname, pv.sold_count AS sold
                FROM product_variants pv
                JOIN products p ON pv.product_id = p.id
                WHERE pv.stock > 0
                ORDER BY pv.sold_count DESC
                LIMIT 5
            """)
            rows = cur.fetchall()
            conn.close()
        except Exception as e:
            return f"Gagal mengambil data terlaris: {e}"

        if not rows:
            return "Data terlaris belum tersedia."

        return "\n".join([
            "Produk terlaris:"
        ] + [
            f"- {r['pname']} {r['vname']} (terjual: {r['sold']})"
            for r in rows
        ])

    # Menu harian
    if "menu" in ql:
        if not APP_OK:
            return "Fitur menu tidak tersedia."

        offset = 1 if "besok" in ql else 0
        date = (datetime.now().date() + timedelta(days=offset)).isoformat()

        try:
            items = get_daily_menu_from_db(date)
        except Exception as e:
            return f"Gagal mengambil menu: {e}"

        if not items:
            return f"Menu untuk {date} belum tersedia."

        return "\n".join(
            [f"Menu untuk {date}:"] +
            [f"- {it['name']} {it.get('variant_name','')} → Rp{int(it['price']):,}" for it in items]
        )

    # Greetings
    if any(k in ql for k in ["halo", "hai", "hello"]):
        return "Halo! Silakan tanya 'menu hari ini', 'lokasi', atau 'cek harga [produk]' 😊"

    return None
# ---- PROCESS MESSAGE (ANTI-FREEZE FIX) ----
def process_message(q: str):
    import traceback

    q_str = (q or "").strip()
    if not q_str:
        return

    # ---- Anti-freeze: jangan proses jika masih locked ----
    if st.session_state.get("processing_lock"):
        return

    st.session_state.processing_lock = True

    # ---- Simpan pesan user ----
    st.session_state.chat_history.append({
        "who": "user",
        "text": escape(q_str),
        "ts": datetime.now().isoformat()
    })

    ql = q_str.lower()

    # Intent untuk memaksa Gemini
    force_gemini_intent = any(k in ql for k in ["rekomendasi", "sarankan", "saran"])

    # Intent untuk memaksa lokal saja
    forced_local = any(k in ql for k in [
        "termurah", "terlaris", "harga", "menu", "lokasi", "alamat", "stok", "cek harga"
    ])

    status = st.empty()
    overlay = st.empty()
    bot_reply = None

    try:
        # =========================================
        #  MODE DECISION: LOCAL VS GEMINI
        # =========================================
        use_gemini = False
        if GEMINI_API_KEY and not forced_local:
            if force_gemini_intent or st.session_state.get("use_gemini_ui"):
                use_gemini = True

        # =========================================
        #  MODE GEMINI
        # =========================================
        if use_gemini:
            overlay.markdown("""
            <div class="chat-overlay">
                <div class="typing-box">
                    <div class="typing-line">Menghubungi Gemini... Mohon tunggu</div>
                    <div class="dots"><span></span><span></span><span></span></div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            status.info("Menghubungi Gemini...")

            # siapkan konteks dari database dan toko
            lokasi_info, prod_summary = _build_context_for_gemini()

            base_system = (
                "Kamu adalah asisten toko online. "
                "Jawab singkat, jelas, ramah, dan langsung ke poin. "
                "Jangan berikan link/alamat/maps kecuali jika user bertanya eksplisit."
            )

            full_system = base_system
            if prod_summary:
                full_system += "\n\nRingkasan produk:\n" + prod_summary
            if lokasi_info:
                full_system += "\n\nData toko:\n" + lokasi_info

            bot_reply = _call_gemini(
                f"Pertanyaan pengguna: {q_str}\nJawab jelas dan ringkas.",
                GEMINI_API_KEY,
                full_system
            )

            status.empty()
            overlay.empty()

        # =========================================
        #  MODE LOKAL
        # =========================================
        else:
            bot_reply = local_logic(q_str)

        # fallback jika local logic tidak balas
        if not bot_reply:
            bot_reply = "Maaf, saya tidak mengerti pertanyaan Anda."

        # simpan balasan bot
        st.session_state.chat_history.append({
            "who": "bot",
            "text": escape(bot_reply),
            "ts": datetime.now().isoformat()
        })
        st.session_state.last_bot_msg = bot_reply

    except Exception as e:
        print("ERROR process_message:", e)
        print(traceback.format_exc())
        st.session_state.chat_history.append({
            "who": "bot",
            "text": f"Terjadi error internal: {e}",
            "ts": datetime.now().isoformat()
        })

    finally:
        # ---- ANTI-FREEZE WAJIB ----
        st.session_state.processing_lock = False
        st.session_state.chat_input = ""

        try:
            status.empty()
        except:
            pass

        try:
            overlay.empty()
        except:
            pass
# ==== UI BUILD (HEADER + THEME TOGGLES) ====

logo_path = "logo.png"
if os.path.exists(logo_path):
    logo_html = (
        f'<img src="{logo_path}" '
        'style="width:100%;height:100%;object-fit:cover;border-radius:10px;">'
    )
else:
    logo_html = (
        "<div style='width:100%;height:100%;display:flex;"
        "align-items:center;justify-content:center;font-weight:800'>WBY</div>"
    )

# --- Layout Header ---
col1, col2 = st.columns([8, 2])

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
    # Toggle Gemini
    tooltip = (
        "Jika aktif dan GEMINI_API_KEY tersedia di environment, chatbot akan "
        "menggunakan Gemini. Matikan untuk mode lokal."
    )
    st.session_state.use_gemini_ui = st.checkbox(
        "Gunakan Gemini",
        value=st.session_state.use_gemini_ui,
        help=tooltip
    )

    # Theme toggle
    theme_index = 0 if st.session_state.theme == "dark" else 1
    theme_choice = st.radio(
        "Tema",
        options=["dark", "light"],
        index=theme_index,
        horizontal=True
    )
    st.session_state.theme = theme_choice


# ==== APPLY PAGE-LEVEL THEME CSS ====

if st.session_state.theme == "light":
    st.markdown("""
    <style>
      .stApp {
        background-color: #f2f4f8 !important;
        color: #0b1220 !important;
      }
      h1,h2,h3,h4,h5,h6,p,label,.stMarkdown {
        color: #0b1220 !important;
      }
      div[data-testid="stButton"] button {
        background-color: #ffffff !important;
        color: #0b1220 !important;
        border: 1px solid #d1d5db !important;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05) !important;
      }
      div[data-testid="stButton"] button:hover {
        background-color: #e0e7ff !important;
        border-color: #39a7ff !important;
      }
      div[data-testid="stTextInput"] input {
        background-color: #ffffff !important;
        color: #0b1220 !important;
        border:1px solid #d1d5db !important;
      }
      div[data-testid="stTextInput"] input::placeholder {
        color: #6b7280 !important;
      }
    </style>
    """, unsafe_allow_html=True)

    components.html("""
    <script>
      const body = window.parent.document.body;
      body.classList.add('chat-light');
      body.classList.remove('chat-dark');
    </script>
    """, height=0, width=0)

else:  # DARK MODE
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
# ==== MESSAGES RENDERING ====
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


# ==== Auto-scroll + focus helper (MutationObserver) ====
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

      // observer to auto-scroll when new messages are added
      if(container){
        const obs = new MutationObserver((mutations) => {
          let added = mutations.some(m => m.addedNodes && m.addedNodes.length > 0);
          if(added){
            setTimeout(()=>scrollToBottom(true), 40);
          }
        });
        obs.observe(container, { childList: true, subtree: false });
      }

      // try focus on chat input
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


# ==== Quick replies ====
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


# ==== Input area ====
def handle_input():
    user_text = st.session_state.get("chat_input_field", "")
    if user_text and user_text.strip():
        process_message(user_text)
        st.session_state.chat_input_field = ""

st.markdown('<div class="input-bar">', unsafe_allow_html=True)

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


# ==== Footer / Note ====
gemini_note = "Gemini aktif (ENV key tersedia)" if DEFAULT_USE_GEMINI else "Gemini tidak dikonfigurasi (ENV GEMINI_API_KEY kosong)"
st.markdown(f'<div class="note">Chatbot terhubung dengan <code>app.py</code>. {gemini_note}. Toggle di header bisa override mode Gemini. Tema: {st.session_state.theme}.</div>', unsafe_allow_html=True)
st.markdown('</div></div>', unsafe_allow_html=True)
