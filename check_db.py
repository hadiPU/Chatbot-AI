# check_db.py
import sqlite3, os, json, sys

DB = "db.sqlite"
if not os.path.exists(DB):
    print("File db.sqlite TIDAK DITEMUKAN di folder. Pastikan kamu sudah menjalankan app.py setidaknya sekali.")
    sys.exit(0)

conn = sqlite3.connect(DB)
cur = conn.cursor()

def safe_fetch(q):
    try:
        cur.execute(q)
        return cur.fetchall()
    except Exception as e:
        return f"ERROR: {e}"

print("=== INFO TABEL ===")
tables = safe_fetch("SELECT name FROM sqlite_master WHERE type='table';")
print("Tables:", tables)

print("\n=== JUMLAH BARIS ===")
for t in ["products","product_variants","orders","order_items"]:
    res = safe_fetch(f"SELECT count(*) FROM {t};")
    print(f"{t}: {res}")

print("\n=== SAMPLE products (5) ===")
prod = safe_fetch("SELECT id, sku, name, category, image_path FROM products LIMIT 5;")
print(prod)

print("\n=== SAMPLE product_variants (10) ===")
pv = safe_fetch("SELECT id, product_id, variant_name, price, stock FROM product_variants LIMIT 10;")
print(pv)

# show any errors from import logs? try to read products.json existence
print("\n=== Cek products.json ada di folder? ===")
print("products.json exists:", os.path.exists("products.json"))

conn.close()
