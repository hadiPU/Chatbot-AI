# app.py — Final version (Gemini 2.5-flash, top-seller, robust cart & checkout)
import streamlit as st
import sqlite3
import json
import os
from datetime import datetime

# ----------------------------------------
# Gemini (Google Generative AI) SDK
# pip install google-generativeai
# ----------------------------------------
USE_GEMINI_LIB = True
try:
    import google.generativeai as genai
except Exception:
    USE_GEMINI_LIB = False

DB_PATH = "db.sqlite"
PRODUCTS_JSON = "products.json"
INIT_SQL = "init_db.sql"

# Logo candidates (sesuaikan jika perlu)
POSSIBLE_LOGOS = [
    "/mnt/data/ce279cc8-3687-46dd-a006-06c0147b6faa.png",
    "ce279cc8-3687-46dd-a006-06c0147b6faa.png",
    "mie-telur.jpg",
    "logo.png"
]

LOGO_PATH = None
for p in POSSIBLE_LOGOS:
    if os.path.exists(p):
        LOGO_PATH = p
        break

# ---------------- DB helpers ----------------
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # jalankan init_db.sql jika ada
    if os.path.exists(INIT_SQL):
        sql = open(INIT_SQL, "r", encoding="utf-8").read()
        cur.executescript(sql)
        conn.commit()

    # safety: jika tabel belum ada, buat struktur default
    try:
        cur.execute("SELECT COUNT(*) as c FROM products")
        cnt = cur.fetchone()["c"]
    except Exception:
        cur.executescript("""
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS products (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          sku TEXT UNIQUE,
          name TEXT NOT NULL,
          category TEXT,
          description TEXT,
          image_path TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS product_variants (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          product_id INTEGER NOT NULL,
          variant_name TEXT NOT NULL,
          price INTEGER NOT NULL,
          stock INTEGER NOT NULL DEFAULT 0,
          sold_count INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS orders (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_name TEXT,
          customer_phone TEXT,
          total INTEGER,
          status TEXT DEFAULT 'pending',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS order_items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          order_id INTEGER NOT NULL,
          product_id INTEGER NOT NULL,
          variant_id INTEGER,
          qty INTEGER NOT NULL,
          price INTEGER NOT NULL,
          FOREIGN KEY(order_id) REFERENCES orders(id),
          FOREIGN KEY(product_id) REFERENCES products(id),
          FOREIGN KEY(variant_id) REFERENCES product_variants(id)
        );
        CREATE TRIGGER IF NOT EXISTS trg_update_sales
        AFTER INSERT ON order_items
        FOR EACH ROW
        BEGIN
            UPDATE product_variants
            SET sold_count = sold_count + NEW.qty
            WHERE id = NEW.variant_id;
        END;
        """)
        conn.commit()
        cur.execute("SELECT COUNT(*) as c FROM products")
        cnt = cur.fetchone()["c"]

    # import products.json jika tabel kosong
    if cnt == 0 and os.path.exists(PRODUCTS_JSON):
        with open(PRODUCTS_JSON, "r", encoding="utf-8") as f:
            items = json.load(f)
        for p in items:
            cur.execute(
                "INSERT INTO products (sku,name,category,description,image_path) VALUES (?,?,?,?,?)",
                (p.get("sku"), p.get("name"), p.get("category", ""), p.get("description", ""), p.get("image_path", ""))
            )
            pid = cur.lastrowid
            for v in p.get("variants", []):
                cur.execute(
                    "INSERT INTO product_variants (product_id, variant_name, price, stock, sold_count) VALUES (?,?,?,?,?)",
                    (pid, v.get("variant_name"), v.get("price", 0), v.get("stock", 0), 0)
                )
        conn.commit()

    conn.close()


def list_products():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT p.id as pid, p.sku, p.name, p.category, p.description, p.image_path,
               pv.id as vid, pv.variant_name, pv.price, pv.stock, pv.sold_count
        FROM products p JOIN product_variants pv ON p.id=pv.product_id
        ORDER BY p.id
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def get_product_summary_text(limit=12):
    rows = list_products()
    lines = []
    seen = set()
    for r in rows:
        if r["pid"] in seen:
            continue
        seen.add(r["pid"])
        lines.append(f"{r['name']} ({r['category']}), varian contoh: {r['variant_name']} Rp{r['price']:,}")
        if len(lines) >= limit:
            break
    return "\n".join(lines)


# add_order with robustness
def add_order(customer_name, customer_phone, cart_items):
    conn = get_conn()
    cur = conn.cursor()

    total = 0
    # hitung total aman
    for item in cart_items:
        price = int(item.get("price") or 0)
        qty = int(item.get("qty") or 0)
        total += price * qty

    cur.execute("INSERT INTO orders (customer_name, customer_phone, total) VALUES (?,?,?)",
                (customer_name, customer_phone, total))
    oid = cur.lastrowid

    for it in cart_items:
        product_id = it.get("product_id") or it.get("pid")
        variant_id = it.get("variant_id") or it.get("vid")
        qty = int(it.get("qty") or 0)
        price = int(it.get("price") or 0)

        if not product_id or qty <= 0:
            continue

        cur.execute("INSERT INTO order_items (order_id, product_id, variant_id, qty, price) VALUES (?,?,?,?,?)",
                    (oid, product_id, variant_id, qty, price))

        # update stok dan sold_count
        if variant_id:
            cur.execute("UPDATE product_variants SET stock = stock - ? WHERE id = ?", (qty, variant_id))
            try:
                cur.execute("UPDATE product_variants SET sold_count = sold_count + ? WHERE id = ?", (qty, variant_id))
            except Exception:
                pass
        else:
            # fallback: kurangi stock varian pertama
            cur.execute("SELECT id FROM product_variants WHERE product_id = ? LIMIT 1", (product_id,))
            row = cur.fetchone()
            if row:
                vid = row["id"]
                cur.execute("UPDATE product_variants SET stock = stock - ? WHERE id = ?", (qty, vid))
                try:
                    cur.execute("UPDATE product_variants SET sold_count = sold_count + ? WHERE id = ?", (qty, vid))
                except Exception:
                    pass

    conn.commit()
    conn.close()
    return oid


# ---------------- Gemini helper ----------------
def call_gemini_chat(user_msg, api_key=None, system_prompt=None, model="gemini-2.5-flash"):
    if not USE_GEMINI_LIB:
        return "Library google-generativeai belum ter-install. Jalankan: pip install google-generativeai"

    final_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not final_key:
        return "API key Gemini tidak ditemukan."

    genai.configure(api_key=final_key)

    prompt = (system_prompt + "\n\n" + user_msg) if system_prompt else user_msg

    try:
        model_engine = genai.GenerativeModel(model)
        response = model_engine.generate_content(
            prompt,
            generation_config={
                "temperature": 0.2,
                "top_p": 1.0,
                "max_output_tokens": 500
            }
        )
        return getattr(response, "text", str(response))
    except Exception as e:
        return f"Error memanggil Gemini API: {e}"


# ---------------- Streamlit UI ----------------
st.set_page_config(page_title="Toko Online + Chatbot", layout="wide")

# Sidebar logo
if LOGO_PATH and os.path.exists(LOGO_PATH):
    st.sidebar.image(LOGO_PATH, width=160)
else:
    st.sidebar.markdown("**Toko Demo**")

st.sidebar.title("Toko Demo")
menu = st.sidebar.selectbox("Menu", ["Katalog", "Keranjang", "Chatbot", "Admin", "Orders"])

# init db jika belum ada
if not os.path.exists(DB_PATH):
    init_db()
else:
    try:
        conn = get_conn()
        conn.execute("SELECT 1 FROM products LIMIT 1").fetchall()
        conn.close()
    except Exception:
        init_db()

# session cart
if "cart" not in st.session_state:
    st.session_state.cart = []
# reload flag (untuk fallback rerun)
if "_reload_flag" not in st.session_state:
    st.session_state["_reload_flag"] = False

# helper: safe rerun fallback
def safe_rerun():
    try:
        st.experimental_rerun()
    except AttributeError:
        st.session_state["_reload_flag"] = not st.session_state.get("_reload_flag", False)
        st.stop()


# ---------------- Katalog ----------------
if menu == "Katalog":
    st.header("Katalog Produk")
    rows = list_products()
    if not rows:
        st.info("Belum ada produk. Import di Admin.")
    else:
        for r in rows:
            st.markdown("---")
            cols = st.columns([1, 3])
            with cols[0]:
                if r["image_path"] and os.path.exists(r["image_path"]):
                    st.image(r["image_path"], width=140)
                elif LOGO_PATH and os.path.exists(LOGO_PATH):
                    st.image(LOGO_PATH, width=140)
                else:
                    st.write("")
            with cols[1]:
                st.subheader(f"{r['name']} — {r['variant_name']}")
                st.write(f"Kategori: {r['category']}")
                st.write(r["description"])
                st.write(f"Stok: {r['stock']}  •  Harga: Rp {r['price']:,}")

                qty = st.number_input(f"Jumlah ({r['name']} - {r['variant_name']})", min_value=0, max_value=r['stock'], value=0, key=f"q_{r['vid']}")

                if st.button(f"Tambah ke Keranjang ({r['variant_name']})", key=f"a_{r['vid']}"):
                    if qty > 0:
                        # tambahkan item ke cart dengan struktur yang diharapkan add_order
                        st.session_state.cart.append({
                            "product_id": r["pid"],
                            "variant_id": r["vid"],
                            "sku": r["sku"],
                            "name": r["name"],
                            "variant_name": r["variant_name"],
                            "price": r["price"],
                            "qty": qty
                        })
                        st.success("Produk ditambahkan ke keranjang")

# ---------------- Keranjang & Checkout ----------------
elif menu == "Keranjang":
    st.header("Keranjang Belanja")
    cart = st.session_state.cart
    if not cart:
        st.info("Keranjang kosong. Tambah produk di Katalog.")
    else:
        total = sum([c["price"] * c["qty"] for c in cart])
        for i, c in enumerate(cart):
            st.write(f"{i+1}. {c['name']} — {c['variant_name']} x{c['qty']}  → Rp {c['price']*c['qty']:,}")
            if st.button(f"Hapus {i}", key=f"rm_{i}"):
                st.session_state.cart.pop(i)
                safe_rerun()
        st.write("**Total:** Rp {:,}".format(total))
        st.write("---")
        st.subheader("Checkout")
        name = st.text_input("Nama penerima")
        phone = st.text_input("No. HP / Telepon")
        if st.button("Checkout Sekarang"):
            if not name or not phone:
                st.warning("Isi nama dan nomor telepon.")
            else:
                oid = add_order(name, phone, cart)
                st.success(f"Order berhasil dibuat (ID: {oid}). Terima kasih!")
                st.session_state.cart = []

# ---------------- Chatbot ----------------
elif menu == "Chatbot":
    st.header("Chatbot Produk (jawab pakai data lokal atau Gemini API)")
    st.write("1. Jawaban lokal menggunakan data di database (cepat, tanpa biaya).")
    st.write("2. Jika ingin jawaban lebih natural, centang 'Gunakan Gemini API' lalu isi API key di environment.")
    use_api = st.checkbox("Gunakan Gemini API (opsional)")
    if use_api:
        st.info("Pastikan Anda sudah memasang GEMINI_API_KEY atau GOOGLE_API_KEY di environment, atau masukkan API key di input di bawah.")
        api_key_input = st.text_input("Masukkan Gemini API key (opsional, kalau kosong akan pakai env var)", type="password")
    else:
        api_key_input = None

    model_choice = st.selectbox("Pilih model Gemini", ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro"])

    user_q = st.text_input("Tanya tentang produk / harga / rekomendasi...", key="chat_input")
    if st.button("Kirim Pertanyaan"):
        if not user_q.strip():
            st.warning("Tuliskan pertanyaan dulu.")
        else:
            q_lower = user_q.lower()
            local_answer = None
            conn = get_conn()
            cur = conn.cursor()

            if "termurah" in q_lower or "yang paling murah" in q_lower or "terendah" in q_lower:
                cur.execute("SELECT p.name, pv.price FROM products p JOIN product_variants pv ON p.id=pv.product_id ORDER BY pv.price ASC LIMIT 5")
                rows = cur.fetchall()
                if rows:
                    lines = ["Top 5 produk termurah:"]
                    for r in rows:
                        lines.append(f"- {r['name']} Rp {r['price']:,}")
                    local_answer = "\n".join(lines)

            elif "termahal" in q_lower or "mahal" in q_lower or "tertinggi" in q_lower:
                cur.execute("SELECT p.name, pv.price FROM products p JOIN product_variants pv ON p.id=pv.product_id ORDER BY pv.price DESC LIMIT 5")
                rows = cur.fetchall()
                if rows:
                    lines = ["Top 5 produk termahal:"]
                    for r in rows:
                        lines.append(f"- {r['name']} Rp {r['price']:,}")
                    local_answer = "\n".join(lines)

            elif "harga" in q_lower:
                terms = [t for t in q_lower.replace('?', ' ').split() if len(t) > 2]
                found = []
                for t in terms[::-1]:
                    cur.execute("SELECT p.name, pv.variant_name, pv.price FROM products p JOIN product_variants pv ON p.id=pv.product_id WHERE lower(p.name) LIKE ? OR lower(p.category) LIKE ? LIMIT 5", (f"%{t}%", f"%{t}%"))
                    rows = cur.fetchall()
                    if rows:
                        for r in rows:
                            found.append(f"- {r['name']} ({r['variant_name']}) → Rp {r['price']:,}")
                    if found:
                        break
                if found:
                    local_answer = "Saya menemukan produk:\n" + "\n".join(found)

            elif "stok" in q_lower or "tersedia" in q_lower:
                cur.execute("SELECT p.name, pv.variant_name, pv.stock FROM products p JOIN product_variants pv ON p.id=pv.product_id WHERE pv.stock > 0 ORDER BY pv.stock DESC LIMIT 10")
                rows = cur.fetchall()
                lines = ["Produk dengan stok tersedia (top 10):"]
                for r in rows:
                    lines.append(f"- {r['name']} {r['variant_name']} (stok: {r['stock']})")
                local_answer = "\n".join(lines)

            elif "terlaris" in q_lower or "paling laku" in q_lower or "terfavorit" in q_lower:
                cur.execute("SELECT p.name, pv.variant_name, pv.sold_count FROM product_variants pv JOIN products p ON pv.product_id = p.id WHERE pv.sold_count > 0 ORDER BY pv.sold_count DESC LIMIT 10")
                rows = cur.fetchall()
                if rows:
                    lines = ["Top Produk Terlaris (berdasarkan jumlah terjual):"]
                    for r in rows:
                        lines.append(f"- {r['name']} {r['variant_name']} (terjual: {r['sold_count']})")
                    local_answer = "\n".join(lines)
                else:
                    local_answer = "Belum ada data penjualan."

            conn.close()

            if local_answer and not use_api:
                st.subheader("Jawaban (dari data lokal)")
                st.text(local_answer)
            else:
                system_prompt = "Kamu adalah asisten penjualan untuk toko online. Jawab singkat, jelas, dan akurat. Jika ditanya soal produk, gunakan data yang diberikan."
                # ringkasan produk
                prod_summary = get_product_summary_text(limit=15)
                # ambil top seller dari database untuk disertakan ke prompt
                try:
                    conn2 = get_conn()
                    cur2 = conn2.cursor()
                    cur2.execute("""
                        SELECT p.name, pv.variant_name, pv.sold_count
                        FROM product_variants pv
                        JOIN products p ON pv.product_id = p.id
                        WHERE pv.sold_count > 0
                        ORDER BY pv.sold_count DESC
                        LIMIT 10
                    """)
                    ts = cur2.fetchall()
                    conn2.close()
                    if ts:
                        top_lines = [f"- {r['name']} {r['variant_name']} (terjual: {r['sold_count']})" for r in ts]
                        top_text = "\n".join(top_lines)
                    else:
                        top_text = "Belum ada data penjualan."
                except Exception:
                    top_text = "Belum ada data penjualan."

                full_system = system_prompt + "\n\nData produk (ringkasan):\n" + prod_summary + "\n\nData produk terlaris:\n" + top_text

                if use_api:
                    if not USE_GEMINI_LIB:
                        st.error("Library google-generativeai belum ter-install. Jalankan: pip install google-generativeai")
                    else:
                        st.subheader("Jawaban (menggunakan Gemini API)")
                        api_key = api_key_input.strip() if api_key_input else os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
                        if not api_key:
                            st.error("API key tidak ditemukan. Set environment variable GEMINI_API_KEY atau masukkan di input.")
                        else:
                            with st.spinner("Menghubungi Gemini..."):
                                ans = call_gemini_chat(user_q, api_key=api_key, system_prompt=full_system, model=model_choice)
                                st.write(ans)
                else:
                    st.subheader("Jawaban (fallback lokal)")
                    st.write("Maaf, saya tidak menemukan jawaban spesifik di data lokal untuk pertanyaan itu. Coba tanya 'harga [nama produk]' atau 'produk termurah'.")

# ---------------- Admin ----------------
elif menu == "Admin":
    st.header("Admin - Import Produk & Lihat Stock")
    if st.button("Import dari products.json (jika belum diimport)"):
        init_db()
        st.success("Import selesai (jika file products.json tersedia).")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT p.id, p.sku, p.name, p.category, pv.variant_name, pv.price, pv.stock, pv.sold_count FROM products p JOIN product_variants pv ON p.id=pv.product_id ORDER BY p.id")
    rows = cur.fetchall()
    conn.close()
    if rows:
        st.write("Daftar Produk / Varian:")
        for r in rows:
            st.write(f"{r['sku']} | {r['name']} - {r['variant_name']} | Rp {r['price']:,} | Stok: {r['stock']} | Terjual: {r['sold_count']}")
    else:
        st.info("Belum ada produk. Import products.json")

# ---------------- Orders ----------------
elif menu == "Orders":
    st.header("Daftar Orders")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders ORDER BY id DESC")
    orders = cur.fetchall()
    if not orders:
        st.info("Belum ada order.")
    for o in orders:
        st.write(f"Order ID: {o['id']} | Nama: {o['customer_name']} | Total: Rp {o['total']:,} | Status: {o['status']} | {o['created_at']}")
        cur2 = conn.cursor()
        cur2.execute("SELECT oi.qty, oi.price, p.name, pv.variant_name FROM order_items oi JOIN products p ON oi.product_id=p.id LEFT JOIN product_variants pv ON oi.variant_id=pv.id WHERE oi.order_id=?", (o['id'],))
        items = cur2.fetchall()
        for it in items:
            st.write(f"- {it['name']} {it['variant_name']} x{it['qty']} → Rp {it['price']*it['qty']:,}")
    conn.close()
