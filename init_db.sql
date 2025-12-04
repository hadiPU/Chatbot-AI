PRAGMA foreign_keys = ON;

-- Tabel products
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sku TEXT UNIQUE,
  name TEXT NOT NULL,
  category TEXT,
  description TEXT,
  image_path TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Tabel product_variants
CREATE TABLE IF NOT EXISTS product_variants (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER NOT NULL,
  variant_name TEXT NOT NULL,
  price INTEGER NOT NULL,
  stock INTEGER NOT NULL DEFAULT 0,
  sold_count INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
);

-- Tabel stores (lokasi / cabang)
CREATE TABLE IF NOT EXISTS stores (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  address TEXT,
  phone TEXT,
  latitude REAL,
  longitude REAL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Tabel orders (simpan store_id & delivery_address)
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

-- Tabel order_items
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

-- Tabel daily_menus
CREATE TABLE IF NOT EXISTS daily_menus (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  menu_date TEXT UNIQUE,
  items_json TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  generated_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_daily_menus_menu_date ON daily_menus(menu_date);

-- Trigger: update sold_count setiap insert ke order_items
-- DROP terlebih dahulu jika sudah ada (menghindari error saat re-run)
DROP TRIGGER IF EXISTS trg_update_sales;

CREATE TRIGGER trg_update_sales
AFTER INSERT ON order_items
FOR EACH ROW
BEGIN
    UPDATE product_variants
    SET sold_count = sold_count + NEW.qty
    WHERE id = NEW.variant_id;
END;
