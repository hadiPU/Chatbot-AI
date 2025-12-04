# app.py - Toko Online + Chatbot + Daily Menu + Stores + maps_url (final)
# Simpan sebagai app.py dan jalankan: streamlit run app.py
# NOTE: UI Streamlit dibungkus di dalam main() sehingga file ini bisa di-import oleh chatbot_only.py tanpa mengeksekusi UI.

import sqlite3
import json
import os
import random
import re
import urllib.parse
from datetime import datetime, timedelta
from dotenv import load_dotenv

# timezone Jakarta (opsional)
try:
    import zoneinfo
    JAKARTA = zoneinfo.ZoneInfo("Asia/Jakarta")
except Exception:
    JAKARTA = None

# Gemini SDK (opsional)
USE_GEMINI_LIB = False
load_dotenv()
try:
    import google.genai as genai
    from google.genai import types
    USE_GEMINI_LIB = True
except Exception:
    USE_GEMINI_LIB = False

DB_PATH = "db.sqlite"
INIT_SQL = "init_db.sql"
PRODUCTS_JSON = "products.json"

# ---------------- DB helpers ----------------
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
    except Exception:
        pass
    return conn

def ensure_maps_url_column():
    """Pastikan kolom maps_url ada di tabel stores. Jika belum, tambahkan."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA table_info(stores)")
        cols = cur.fetchall()
        col_names = [c["name"] for c in cols]
        if "maps_url" not in col_names:
            # tambahkan kolom secara aman
            try:
                cur.execute("ALTER TABLE stores ADD COLUMN maps_url TEXT")
                conn.commit()
            except Exception:
                # jika gagal (mis. SQLite versi lama atau constraints), ignore
                pass
    except Exception:
        pass
    conn.close()

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    # jalankan file init_db.sql jika ada
    if os.path.exists(INIT_SQL):
        with open(INIT_SQL, "r", encoding="utf-8") as f:
            sql = f.read()
        try:
            cur.executescript(sql)
            conn.commit()
        except Exception:
            pass

    # safety: jika tabel belum ada, buat struktur minimal (fallback)
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

        CREATE TABLE IF NOT EXISTS stores (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          address TEXT,
          phone TEXT,
          latitude REAL,
          longitude REAL,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS orders (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_name TEXT,
          customer_phone TEXT,
          total INTEGER,
          status TEXT DEFAULT 'pending',
          store_id INTEGER,
          delivery_address TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(store_id) REFERENCES stores(id)
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

        CREATE TABLE IF NOT EXISTS daily_menus (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          menu_date TEXT UNIQUE,
          items_json TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          generated_by TEXT
        );
        """)
        conn.commit()
        try:
            cur.execute("SELECT COUNT(*) as c FROM products")
            cnt = cur.fetchone()["c"]
        except Exception:
            cnt = 0

    conn.close()
    # pastikan kolom maps_url ada
    ensure_maps_url_column()

# Pastikan init_db dijalankan di awal (tetap dilakukan pada import)
if not os.path.exists(DB_PATH):
    init_db()
else:
    try:
        conn = get_conn()
        conn.execute("SELECT 1 FROM products LIMIT 1").fetchall()
        conn.close()
        ensure_maps_url_column()
    except Exception:
        init_db()

# ---------------- Data import helper ----------------
def import_products_from_json():
    if not os.path.exists(PRODUCTS_JSON):
        return 0
    conn = get_conn()
    cur = conn.cursor()
    with open(PRODUCTS_JSON, "r", encoding="utf-8") as f:
        items = json.load(f)
    count = 0
    for p in items:
        try:
            cur.execute("INSERT INTO products (sku,name,category,description,image_path) VALUES (?,?,?,?,?)",
                        (p.get("sku"), p.get("name"), p.get("category", ""), p.get("description", ""), p.get("image_path", "")))
            pid = cur.lastrowid
            for v in p.get("variants", []):
                cur.execute("INSERT INTO product_variants (product_id, variant_name, price, stock, sold_count) VALUES (?,?,?,?,?)",
                            (pid, v.get("variant_name"), v.get("price", 0), v.get("stock", 0), v.get("sold_count", 0) if v.get("sold_count") is not None else 0))
            count += 1
        except Exception:
            continue
    conn.commit()
    conn.close()
    return count

# ---------------- Product listing ----------------
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
        lines.append(f"{r['name']} ({r['category']}), contoh varian: {r['variant_name']} Rp{r['price']:,} (stok: {r['stock']})")
        if len(lines) >= limit:
            break
    return "\n".join(lines)

# ---------------- Stores helpers ----------------
def row_to_dict(r):
    """Convert sqlite3.Row to regular dict safely."""
    if r is None:
        return None
    try:
        return {k: r[k] for k in r.keys()}
    except Exception:
        # fallback
        return dict(r)

def add_store(name, address="", phone="", latitude=None, longitude=None, maps_url=None):
    conn = get_conn()
    cur = conn.cursor()
    # gunakan prepared statement, tambahkan maps_url jika kolom ada
    try:
        cur.execute("PRAGMA table_info(stores)")
        cols = [c["name"] for c in cur.fetchall()]
        if "maps_url" in cols:
            cur.execute("INSERT INTO stores (name,address,phone,latitude,longitude,maps_url) VALUES (?,?,?,?,?,?)",
                        (name, address, phone, latitude, longitude, maps_url))
        else:
            cur.execute("INSERT INTO stores (name,address,phone,latitude,longitude) VALUES (?,?,?,?,?)",
                        (name, address, phone, latitude, longitude))
        conn.commit()
        sid = cur.lastrowid
    except Exception:
        sid = None
    conn.close()
    return sid

def list_stores():
    conn = get_conn()
    cur = conn.cursor()
    # ambil semua kolom (maps_url mungkin ada)
    cur.execute("SELECT * FROM stores ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    return rows

def get_store_by_id(sid):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM stores WHERE id=?", (sid,))
    row = cur.fetchone()
    conn.close()
    return row

def maps_url_for_store_row(s):
    """
    Prioritas:
    1) jika ada kolom maps_url dan terisi -> return maps_url (persis)
    2) jika ada latitude & longitude -> return maps search with lat,lon
    3) fallback: encode address -> maps search by address
    """
    d = row_to_dict(s)
    # 1) maps_url persis
    maps_url = d.get("maps_url")
    if maps_url:
        return maps_url
    # 2) lat/lon
    lat = d.get("latitude")
    lon = d.get("longitude")
    if lat not in (None, "") and lon not in (None, ""):
        return f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
    # 3) encode address
    addr = d.get("address") or ""
    if addr:
        encoded = urllib.parse.quote_plus(addr)
        return f"https://www.google.com/maps/search/?api=1&query={encoded}"
    return None

# ---------------- Daily Menu Helpers ----------------
def today_date_str(offset_days=0):
    if JAKARTA:
        d = datetime.now(JAKARTA).date() + timedelta(days=offset_days)
    else:
        d = datetime.now().date() + timedelta(days=offset_days)
    return d.isoformat()

def get_daily_menu_from_db(date_str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT items_json FROM daily_menus WHERE menu_date=?", (date_str,))
    row = cur.fetchone()
    conn.close()
    if row:
        try:
            return json.loads(row["items_json"])
        except Exception:
            return []
    return None

def save_daily_menu_to_db(date_str, items, generated_by="system"):
    conn = get_conn()
    cur = conn.cursor()
    items_json = json.dumps(items, ensure_ascii=False)
    cur.execute("""
        INSERT INTO daily_menus (menu_date, items_json, generated_by)
        VALUES (?,?,?)
        ON CONFLICT(menu_date) DO UPDATE SET items_json=excluded.items_json, generated_by=excluded.generated_by, created_at=CURRENT_TIMESTAMP
    """, (date_str, items_json, generated_by))
    conn.commit()
    conn.close()

def get_recent_variant_ids(days=2):
    vids = set()
    if days <= 0:
        return vids
    conn = get_conn()
    cur = conn.cursor()
    dates = [today_date_str(offset_days=-i) for i in range(1, days+1)]
    placeholders = ",".join(["?"] * len(dates))
    try:
        cur.execute(f"SELECT items_json FROM daily_menus WHERE menu_date IN ({placeholders})", tuple(dates))
        rows = cur.fetchall()
        for r in rows:
            try:
                items = json.loads(r["items_json"])
                for it in items:
                    if isinstance(it, dict) and it.get("vid") is not None:
                        try:
                            vids.add(int(it["vid"]))
                        except Exception:
                            vids.add(it["vid"])
            except Exception:
                continue
    except Exception:
        pass
    conn.close()
    return vids

def generate_menu_for_date(date_str, n_items=6, exclude_out_of_stock=True, prefer_best_sellers=False, seed_based_on_date=True, avoid_recent_days=2):
    conn = get_conn()
    cur = conn.cursor()
    q = "SELECT p.id as pid, pv.id as vid, p.name, pv.variant_name, pv.price, pv.stock, p.image_path, pv.sold_count FROM products p JOIN product_variants pv ON p.id=pv.product_id"
    if exclude_out_of_stock:
        q += " WHERE pv.stock > 0"
    cur.execute(q)
    rows = cur.fetchall()
    conn.close()

    variants = []
    for r in rows:
        variants.append({
            "pid": r["pid"],
            "vid": int(r["vid"]),
            "name": r["name"],
            "variant_name": r["variant_name"],
            "price": r["price"],
            "stock": r["stock"],
            "image_path": r["image_path"],
            "sold_count": r["sold_count"] if "sold_count" in r.keys() else 0
        })

    if not variants:
        return []

    if seed_based_on_date:
        try:
            seed = int(date_str.replace("-", ""))
        except Exception:
            seed = hash(date_str)
        rnd = random.Random(seed)
    else:
        rnd = random.Random()

    recent_vids = get_recent_variant_ids(days=avoid_recent_days) if avoid_recent_days and avoid_recent_days > 0 else set()
    candidates = [v for v in variants if v["vid"] not in recent_vids]

    chosen = []
    if prefer_best_sellers and candidates:
        weights = [max(1, v.get("sold_count", 0)) for v in candidates]
        pick = rnd.choices(candidates, weights=weights, k=min(n_items, len(candidates)))
        seen = set()
        for c in pick:
            if c["vid"] not in seen:
                seen.add(c["vid"])
                chosen.append(c)
    elif candidates and len(candidates) >= n_items:
        chosen = rnd.sample(candidates, k=n_items)
    else:
        if prefer_best_sellers:
            weights = [max(1, v.get("sold_count", 0)) for v in variants]
            pick = rnd.choices(variants, weights=weights, k=min(n_items, len(variants)))
            seen = set()
            for c in pick:
                if c["vid"] not in seen:
                    seen.add(c["vid"])
                    chosen.append(c)
        else:
            chosen = rnd.sample(variants, k=min(n_items, len(variants)))

    for c in chosen:
        for k in list(c.keys()):
            if k not in ("pid", "vid", "name", "variant_name", "price", "image_path", "stock"):
                c.pop(k, None)
    return chosen

def get_or_create_daily_menu(date_str, force_regenerate=False, **gen_kwargs):
    if not force_regenerate:
        items = get_daily_menu_from_db(date_str)
        if items is not None:
            return items, False
    items = generate_menu_for_date(date_str, **gen_kwargs)
    save_daily_menu_to_db(date_str, items)
    return items, True

# ---------------- Orders / cart helpers ----------------
def add_order(customer_name, customer_phone, cart_items, store_id=None, delivery_address=None):
    conn = get_conn()
    cur = conn.cursor()

    total = 0
    for item in cart_items:
        price = int(item.get("price") or 0)
        qty = int(item.get("qty") or 0)
        total += price * qty

    try:
        cur.execute("INSERT INTO orders (customer_name, customer_phone, total, store_id, delivery_address) VALUES (?,?,?,?,?)",
                    (customer_name, customer_phone, total, store_id, delivery_address))
    except Exception:
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

        if variant_id:
            cur.execute("UPDATE product_variants SET stock = stock - ? WHERE id = ?", (qty, variant_id))
            try:
                cur.execute("UPDATE product_variants SET sold_count = sold_count + ? WHERE id = ?", (qty, variant_id))
            except Exception:
                pass
        else:
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
def call_gemini_chat(prompt, api_key, system_prompt, model="gemini-2.5-flash"):
    try:
        client = genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(system_instruction=system_prompt)
        response = client.models.generate_content(model=model, contents=prompt, config=config)
        return response.text
    except Exception as e:
        return f"Gagal memanggil Gemini: {e}"

# ---------------- Streamlit UI ----------------
# Semua kode UI Streamlit dipindahkan ke fungsi main() agar modul ini bisa di-import tanpa mengeksekusi UI.
def main():
    import streamlit as st

    # set_page_config harus dipanggil sekali ketika app dijalankan langsung
    st.set_page_config(page_title="Toko Online + Chatbot", layout="wide")
    st.sidebar.title("Toko Demo")
    menu = st.sidebar.selectbox("Menu", ["Katalog", "Keranjang", "Chatbot", "Admin", "Orders"])

    # session cart
    if "cart" not in st.session_state:
        st.session_state.cart = []

    # ---------------- Katalog ----------------
    if menu == "Katalog":
        st.header("Katalog Produk")
        rows = list_products()
        if not rows:
            st.info("Belum ada produk. Import via Admin.")
        else:
            for r in rows:
                st.markdown("---")
                cols = st.columns([1, 3])
                with cols[0]:
                    if r["image_path"] and os.path.exists(r["image_path"]):
                        st.image(r["image_path"], width=140)
                with cols[1]:
                    st.subheader(f"{r['name']} — {r['variant_name']}")
                    st.write(f"Kategori: {r['category']}")
                    st.write(r["description"])
                    st.write(f"Harga: Rp {r['price']:,}  •  Stok: {r['stock']}")
                    qty = st.number_input(f"Jumlah ({r['name']} - {r['variant_name']})", min_value=0, max_value=r['stock'], value=0, key=f"q_{r['vid']}")
                    if st.button(f"Tambah ke Keranjang ({r['variant_name']})", key=f"a_{r['vid']}"):
                        if qty > 0:
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
                    st.experimental_rerun()
            st.write("**Total:** Rp {:,}".format(total))
            st.write("---")
            st.subheader("Checkout")
            fulfill = st.radio("Metode:", ("Ambil di Toko", "Kirim ke Alamat"))
            store_id = None
            delivery_address = None
            stores = list_stores()
            if fulfill == "Ambil di Toko":
                if stores:
                    sel = st.selectbox("Pilih toko/cabang:", [f"{s['id']}: {s['name']} — {s['address']}" for s in stores])
                    store_id = int(sel.split(":")[0])
                else:
                    st.info("Belum ada data toko. Tambah di Admin.")
            else:
                delivery_address = st.text_area("Alamat pengiriman (lengkap):")
            name = st.text_input("Nama penerima")
            phone = st.text_input("No. HP / Telepon")
            if st.button("Checkout Sekarang"):
                if not name or not phone:
                    st.warning("Isi nama dan nomor telepon.")
                else:
                    oid = add_order(name, phone, cart, store_id=store_id, delivery_address=delivery_address)
                    st.success(f"Order berhasil dibuat (ID: {oid}). Terima kasih!")
                    st.session_state.cart = []

    # ---------------- Chatbot (FINAL: Gemini only when ON; local only when OFF) ----------------
    elif menu == "Chatbot":
        st.header("Chatbot Produk (lokal / Gemini)")
        st.write("Mode default: Lokal. Centang 'Gunakan Gemini API' untuk jawaban generatif.")
        use_api = st.checkbox("Gunakan Gemini API (opsional)")
        if use_api:
            api_key_input = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            if api_key_input:
                st.info("API key ditemukan di environment.")
            else:
                st.warning("API key tidak ditemukan di environment (GEMINI_API_KEY / GOOGLE_API_KEY).")
        model_choice = st.selectbox("Pilih model Gemini", ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash"], key="model_choice_chat")

        user_q = st.text_input("Tanya tentang produk / harga / lokasi / rekomendasi...", key="chat_input2", label_visibility="visible")
        if st.button("Kirim Pertanyaan"):
            if not user_q.strip():
                st.warning("Tuliskan pertanyaan dulu.")
            else:
                q_lower = user_q.lower()
                local_answer = None

                # Ambil stores dan siapkan lokasi_info untuk prompt Gemini saja
                stores = list_stores()
                lokasi_info = ""
                if stores:
                    store_lines_for_prompt = []
                    for s in stores:
                        url = maps_url_for_store_row(s)
                        addr = s["address"] or ""
                        phone = s["phone"] or ""
                        if url:
                            store_lines_for_prompt.append(f"{s['name']} — {addr} (Tel: {phone}) | MAPS: {url}")
                        else:
                            store_lines_for_prompt.append(f"{s['name']} — {addr} (Tel: {phone})")
                    lokasi_info = "\n".join(store_lines_for_prompt)

                # --- rule-based local answers (produk, stok, menu, dll) ---
                conn = get_conn()
                cur = conn.cursor()

                # lokasi (ringkasan tanpa maps)
                if any(k in q_lower for k in ["lokasi", "alamat", "di mana toko", "cabang", "store", "toko terdekat"]):
                    if stores:
                        la = ["Lokasi Toko / Cabang:"]
                        for s in stores:
                            la.append(f"- {s['name']}: {s['address']} (Tel: {s['phone']})")
                        local_answer = "\n".join(la)
                    else:
                        local_answer = "Belum ada data lokasi toko. Silakan tambahkan di Admin."

                # Produk termurah
                if not local_answer and ("termurah" in q_lower or "yang paling murah" in q_lower or "terendah" in q_lower):
                    cur.execute("SELECT p.name, pv.variant_name, pv.price, pv.stock FROM products p JOIN product_variants pv ON p.id=pv.product_id ORDER BY pv.price ASC LIMIT 5")
                    rows = cur.fetchall()
                    if rows:
                        lines = ["Top 5 produk termurah (dengan stok):"]
                        for r in rows:
                            lines.append(f"- {r['name']} {r['variant_name']} → Rp {r['price']:,} (stok: {r['stock']})")
                        local_answer = "\n".join(lines)

                # Produk termahal
                if not local_answer and ("termahal" in q_lower or "mahal" in q_lower or "tertinggi" in q_lower):
                    cur.execute("SELECT p.name, pv.variant_name, pv.price, pv.stock FROM products p JOIN product_variants pv ON p.id=pv.product_id ORDER BY pv.price DESC LIMIT 5")
                    rows = cur.fetchall()
                    if rows:
                        lines = ["Top 5 produk termahal (dengan stok):"]
                        for r in rows:
                            lines.append(f"- {r['name']} {r['variant_name']} → Rp {r['price']:,} (stok: {r['stock']})")
                        local_answer = "\n".join(lines)

                # Harga spesifik
                if not local_answer and "harga" in q_lower:
                    terms = [t for t in q_lower.replace('?', ' ').split() if len(t) > 2]
                    found = []
                    for t in terms[::-1]:
                        cur.execute("SELECT p.name, pv.variant_name, pv.price, pv.stock FROM products p JOIN product_variants pv ON p.id=pv.product_id WHERE lower(p.name) LIKE ? OR lower(pv.variant_name) LIKE ? OR lower(p.category) LIKE ? LIMIT 10",
                                    (f"%{t}%", f"%{t}%", f"%{t}%"))
                        rows = cur.fetchall()
                        if rows:
                            for r in rows:
                                found.append(f"- {r['name']} ({r['variant_name']}) → Rp {r['price']:,} (stok: {r['stock']})")
                        if found:
                            break
                    if found:
                        local_answer = "Saya menemukan produk:\n" + "\n".join(found)

                # Stok
                if not local_answer and ("stok" in q_lower or "tersedia" in q_lower):
                    cur.execute("SELECT p.name, pv.variant_name, pv.stock FROM products p JOIN product_variants pv ON p.id=pv.product_id WHERE pv.stock > 0 ORDER BY pv.stock DESC LIMIT 10")
                    rows = cur.fetchall()
                    lines = ["Produk dengan stok tersedia (top 10):"]
                    for r in rows:
                        lines.append(f"- {r['name']} {r['variant_name']} (stok: {r['stock']})")
                    local_answer = "\n".join(lines)

                # Terlaris
                if not local_answer and ("terlaris" in q_lower or "paling laku" in q_lower or "terfavorit" in q_lower):
                    cur.execute("SELECT p.name, pv.variant_name, pv.sold_count, pv.stock, pv.price FROM product_variants pv JOIN products p ON pv.product_id = p.id WHERE pv.sold_count > 0 ORDER BY pv.sold_count DESC LIMIT 10")
                    rows = cur.fetchall()
                    if rows:
                        lines = ["Top Produk Terlaris (dengan stok):"]
                        for r in rows:
                            lines.append(f"- {r['name']} {r['variant_name']} (terjual: {r['sold_count']}) → Rp {r['price']:,} (stok: {r['stock']})")
                        local_answer = "\n".join(lines)
                    else:
                        local_answer = "Belum ada data penjualan."

                # Menu / rekomendasi
                if not local_answer and ( "menu" in q_lower or any(k in q_lower for k in ["rekomendasi", "sarankan", "saran", "suggest"]) ):
                    if "besok" in q_lower:
                        date_str = today_date_str(offset_days=1)
                    else:
                        m = re.search(r"(\d{4}-\d{2}-\d{2})", q_lower)
                        date_str = m.group(1) if m else today_date_str()
                    items = get_daily_menu_from_db(date_str)
                    if items is None:
                        items, created = get_or_create_daily_menu(date_str,
                                                                  n_items=st.session_state.get("menu_n_items", 6),
                                                                  avoid_recent_days=st.session_state.get("avoid_recent_days", 2),
                                                                  seed_based_on_date=True,
                                                                  exclude_out_of_stock=True,
                                                                  prefer_best_sellers=False)
                    if items:
                        lines = [f"Menu untuk {date_str} (dengan stok):"]
                        for it in items:
                            stock_text = it.get("stock", "tidak diketahui")
                            lines.append(f"- {it.get('name')} {it.get('variant_name')} → Rp {it.get('price'):,} (stok: {stock_text})")
                        local_answer = "\n".join(lines)
                    else:
                        local_answer = f"Maaf, belum ada item menu untuk {date_str}."

                conn.close()

                # --- OUTPUT ---
                if not use_api:
                    # Lokal mode: tampilkan lokasi + local answer (UI)
                    st.subheader("Lokasi Toko")
                    if stores:
                        for s in stores:
                            url = maps_url_for_store_row(s)
                            line = f"- **{s['name']}** — {s['address']} (Tel: {s['phone']})"
                            if url:
                                line += f"\n  \n  👉 [Lihat di Google Maps]({url})"
                            st.markdown(line)
                    else:
                        st.info("Belum ada data toko.")

                    st.subheader("Informasi Produk (lokal)")
                    if local_answer:
                        st.markdown(local_answer.replace("\n", "  \n"))
                    else:
                        st.write("Maaf, tidak menemukan jawaban lokal. Coba tanya 'harga [produk]' atau 'menu hari ini'.")
                else:
                    # Gemini mode: TIDAK tampilkan lokasi/list toko di UI.
                    # Hanya panggil Gemini dan tampilkan jawaban Gemini saja.
                    if not USE_GEMINI_LIB:
                        st.error("Library google-genai belum ter-install. Jalankan: pip install google-genai")
                        if local_answer:
                            st.subheader("Informasi Produk (lokal)")
                            st.markdown(local_answer.replace("\n", "  \n"))
                    else:
                        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
                        if not api_key:
                            st.error("API key Gemini tidak ditemukan di environment.")
                            if local_answer:
                                st.subheader("Informasi Produk (lokal)")
                                st.markdown(local_answer.replace("\n", "  \n"))
                        else:
                            # siapkan system prompt yang menyertakan lokasi_info dan ringkasan produk
                            prod_summary = get_product_summary_text(limit=12)
                            location_keywords = ["lokasi", "alamat", "di mana", "di mana toko", "cabang", "store", "ambil", "pickup", "antar", "kirim", "pengiriman", "cara ambil", "direksi", "arah"]
                            include_location = any(k in q_lower for k in location_keywords)
                            system_prompt = (
                                "Kamu adalah asisten penjualan untuk toko online. Jawab singkat, jelas, dan akurat.\n"
                                "PENTING: Jangan sertakan alamat lengkap atau link Google Maps kecuali pengguna secara eksplisit menanyakan lokasi, arah, cara ambil, atau pengiriman.\n"
                                "Jika pengguna meminta lokasi atau arah, sertakan alamat lengkap dan link Google Maps persis (jika tersedia) di akhir jawaban.\n"
                                "Jika diminta rekomendasi, pertimbangkan menu hari ini dan jelaskan lokasi/cara ambil hanya bila relevan dan diminta."
                            )
                            full_system = system_prompt + "\n\nRingkasan produk:\n" + prod_summary
                            if include_location and lokasi_info:
                                full_system += "\n\nData toko (untuk lokasi jika diminta):\n" + lokasi_info
                            if local_answer:
                                full_system += "\n\nInformasi lokal yang relevan:\n" + local_answer
                            final_prompt = f"Pertanyaan: {user_q}\n\nJawab singkat dan gunakan data di atas jika relevan. "
                            if include_location:
                                final_prompt += "Karena pengguna menanyakan lokasi/pickup/delivery, sertakan alamat lengkap dan link Google Maps persis jika tersedia."
                            else:
                                final_prompt += "JANGAN sertakan alamat lengkap atau link Google Maps kecuali pengguna meminta lokasi."

                            with st.spinner(f"Menghubungi {model_choice}..."):
                                ans = call_gemini_chat(final_prompt, api_key, full_system, model=model_choice)
                                # Tampilkan HANYA jawaban Gemini
                                st.subheader("Jawaban Gemini")
                                st.markdown(ans)

    # ---------------- Admin ----------------
    elif menu == "Admin":
        st.header("Admin - Produk, Store, Daily Menu")
        col1, col2 = st.columns([2,1])

        with col1:
            if st.button("Import dari products.json (jika ada)"):
                n = import_products_from_json()
                st.success(f"Import selesai. Produk di-file: {n}")

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

        with col2:
            st.subheader("Manajemen Toko")
            with st.form("add_store_form", clear_on_submit=True):
                s_name = st.text_input("Nama Toko")
                s_address = st.text_area("Alamat")
                s_phone = st.text_input("Telepon")
                s_lat = st.text_input("Latitude (optional)")
                s_lon = st.text_input("Longitude (optional)")
                s_maps = st.text_input("Maps URL (paste link Google Maps persis jika ada, optional)")
                if st.form_submit_button("Tambah Toko"):
                    lat = float(s_lat) if s_lat.strip() else None
                    lon = float(s_lon) if s_lon.strip() else None
                    add_store(s_name, s_address, s_phone, lat, lon, s_maps if s_maps.strip() else None)
                    st.success("Toko ditambahkan.")
            stores = list_stores()
            if stores:
                st.write("Daftar Toko:")
                for s in stores:
                    md = f"- {s['id']}: **{s['name']}** — {s['address']} (Tel: {s['phone']})"
                    # tampilkan maps_url jika ada
                    try:
                        mapsu = s["maps_url"]
                    except Exception:
                        mapsu = None
                    if mapsu:
                        md += f"  \n  [Lihat di Google Maps]({mapsu})"
                    st.markdown(md)
            else:
                st.info("Belum ada data toko.")

            st.markdown("---")
            st.subheader("Daily Menu")
            t = st.date_input("Tanggal menu", datetime.now().date())
            t_str = t.isoformat()
            n_items = st.number_input("Jumlah item menu per hari", min_value=1, max_value=20, value=6)
            avoid_days = st.number_input("Hindari varian dari X hari terakhir", min_value=0, max_value=30, value=2)
            if st.button("Generate menu untuk tanggal (jika belum ada)"):
                items, created = get_or_create_daily_menu(t_str, n_items=n_items, avoid_recent_days=avoid_days)
                if created:
                    st.success(f"Menu untuk {t_str} berhasil digenerate dan disimpan.")
                else:
                    st.info(f"Menu untuk {t_str} sudah ada (tidak digenerate ulang).")
                if items:
                    st.write("Menu:")
                    for it in items:
                        st.write(f"- {it.get('name')} {it.get('variant_name')} → Rp {it.get('price'):,} (stok: {it.get('stock')})")
                else:
                    st.warning("Tidak ada item untuk menu ini.")
            if st.button("Regenerate (paksa) untuk tanggal"):
                items, created = get_or_create_daily_menu(t_str, force_regenerate=True, n_items=n_items, avoid_recent_days=avoid_days)
                st.success(f"Menu untuk {t_str} telah di-regenerate (force).")
                if items:
                    for it in items:
                        st.write(f"- {it.get('name')} {it.get('variant_name')} → Rp {it.get('price'):,} (stok: {it.get('stock')})")

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
            st.markdown("---")
            st.write(f"Order ID: {o['id']} | Nama: {o['customer_name']} | Total: Rp {o['total']:,} | Status: {o['status']} | {o['created_at']}")
            if o["store_id"]:
                s = get_store_by_id(o["store_id"])
                if s:
                    st.write(f"Ambil di: {s['name']} — {s['address']}")
                    url = maps_url_for_store_row(s)
                    if url:
                        st.markdown(f"[Lihat di Google Maps]({url})")
            if o["delivery_address"]:
                st.write(f"Alamat kirim: {o['delivery_address']}")
            cur2 = conn.cursor()
            cur2.execute("SELECT oi.qty, oi.price, p.name, pv.variant_name FROM order_items oi JOIN products p ON oi.product_id=p.id LEFT JOIN product_variants pv ON oi.variant_id=pv.id WHERE oi.order_id=?", (o['id'],))
            items = cur2.fetchall()
            for it in items:
                st.write(f"- {it['name']} {it['variant_name']} x{it['qty']} → Rp {it['price']*it['qty']:,}")
        conn.close()

# Hanya jalankan UI ketika skrip dieksekusi langsung
if __name__ == "__main__":
    main()
