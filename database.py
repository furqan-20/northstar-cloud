"""SQLite for local development; PostgreSQL for shared cloud state."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
from datetime import datetime, timezone
from catalog import PRODUCTS

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None

IntegrityError = (sqlite3.IntegrityError,) + ((psycopg.IntegrityError,) if psycopg else ())

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("NORTHSTAR_DATA_DIR", str(BASE / "instance")))

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000).hex()
    return f"pbkdf2-sha256$600000${salt}${digest}"

def password_matches(password, encoded):
    import hmac
    try:
        algorithm, rounds, salt, stored = encoded.split("$")
        calculated = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return algorithm == "pbkdf2-sha256" and hmac.compare_digest(calculated, stored)
    except (ValueError, TypeError):
        return False

def uses_postgres():
    return bool(os.environ.get("DATABASE_URL") or os.environ.get("NORTHSTAR_DB_HOST"))


class DatabaseRow(dict):
    """Keep named and positional access compatible with the original route code."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class PostgresCursor:
    def __init__(self, cursor, lastrowid=None):
        self.cursor, self.lastrowid = cursor, lastrowid

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def fetchone(self):
        row = self.cursor.fetchone()
        return DatabaseRow(row) if row is not None else None

    def fetchall(self):
        return [DatabaseRow(row) for row in self.cursor.fetchall()]

    def __iter__(self):
        return (DatabaseRow(row) for row in self.cursor)


class PostgresConnection:
    """Small adapter for the application's existing, parameterized SQL statements.

    SQL comes only from the source, never from request text. Explicit SQLite write
    transactions use an advisory transaction lock on PostgreSQL, preserving the
    original serialization across multiple application workers/containers.
    """
    id_tables = {'users', 'products', 'addresses', 'orders', 'order_items',
                 'order_events', 'tickets'}

    def __init__(self, connection):
        self.connection = connection

    def execute(self, statement, parameters=()):
        import re
        if statement.strip().upper() == 'BEGIN IMMEDIATE':
            cursor = self.connection.execute('SELECT pg_advisory_xact_lock(78123641)')
            return PostgresCursor(cursor)
        sql = statement.replace('?', '%s').replace('instr(', 'strpos(')
        sql = sql.replace('name COLLATE NOCASE', 'LOWER(name)')
        ignored = sql.lstrip().upper().startswith('INSERT OR IGNORE INTO ')
        if ignored:
            sql = sql.replace('INSERT OR IGNORE INTO', 'INSERT INTO', 1)
            sql += ' ON CONFLICT DO NOTHING'
        insert = re.match(r'\s*INSERT INTO\s+(\w+)', sql, re.IGNORECASE)
        returning = insert and insert.group(1).lower() in self.id_tables
        if returning:
            sql += ' RETURNING id'
        cursor = self.connection.execute(sql, parameters)
        lastrowid = cursor.fetchone()['id'] if returning else None
        return PostgresCursor(cursor, lastrowid)

    def executescript(self, script):
        for statement in script.split(';'):
            if statement.strip():
                self.connection.execute(statement)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


def connect():
    if uses_postgres():
        if psycopg is None:
            raise RuntimeError('Install requirements.txt to use PostgreSQL.')
        if os.environ.get('DATABASE_URL'):
            connection = psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row,
                                         connect_timeout=10)
        else:
            sslmode = os.environ.get('NORTHSTAR_DB_SSLMODE', 'verify-full')
            options = dict(host=os.environ['NORTHSTAR_DB_HOST'],
                           port=int(os.environ.get('NORTHSTAR_DB_PORT', '5432')),
                           dbname=os.environ.get('NORTHSTAR_DB_NAME', 'northstar'),
                           user=os.environ['NORTHSTAR_DB_USER'],
                           password=os.environ['NORTHSTAR_DB_PASSWORD'],
                           sslmode=sslmode, row_factory=dict_row, connect_timeout=10)
            if sslmode == 'verify-full':
                options['sslrootcert'] = os.environ.get('NORTHSTAR_DB_SSLROOTCERT',
                                                        '/etc/ssl/certs/rds/global-bundle.pem')
            connection = psycopg.connect(**options)
        return PostgresConnection(connection)
    if os.environ.get('NORTHSTAR_REQUIRE_POSTGRES') == '1':
        raise RuntimeError('Cloud containers require PostgreSQL configuration.')
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA / 'northstar.sqlite3', timeout=20)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=20000')
    return db

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT 'customer',
 created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
 id TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
 csrf TEXT NOT NULL, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS products (
 id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL, category TEXT NOT NULL,
 price INTEGER NOT NULL CHECK(price>0), compare_price INTEGER, description TEXT NOT NULL,
 specs TEXT NOT NULL, image TEXT NOT NULL, color TEXT NOT NULL, badge TEXT NOT NULL DEFAULT '',
 stock INTEGER NOT NULL CHECK(stock>=0), featured INTEGER NOT NULL DEFAULT 0,
 active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS carts (
 owner TEXT NOT NULL, product_id INTEGER NOT NULL REFERENCES products(id),
 quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 20), PRIMARY KEY(owner,product_id));
CREATE TABLE IF NOT EXISTS cart_coupons (owner TEXT PRIMARY KEY, code TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS wishlist (
 user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
 product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
 created_at TEXT NOT NULL, PRIMARY KEY(user_id,product_id));
CREATE TABLE IF NOT EXISTS addresses (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 label TEXT NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL, line1 TEXT NOT NULL,
 line2 TEXT NOT NULL DEFAULT '', city TEXT NOT NULL, postal_code TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS orders (
 id INTEGER PRIMARY KEY, number TEXT UNIQUE NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id),
 status TEXT NOT NULL, subtotal INTEGER NOT NULL, discount INTEGER NOT NULL, shipping INTEGER NOT NULL,
 total INTEGER NOT NULL, coupon TEXT NOT NULL DEFAULT '', address TEXT NOT NULL,
 payment_method TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
 idempotency_key TEXT NOT NULL, UNIQUE(user_id,idempotency_key));
CREATE TABLE IF NOT EXISTS order_items (
 id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
 product_id INTEGER NOT NULL REFERENCES products(id), name TEXT NOT NULL, image TEXT NOT NULL,
 price INTEGER NOT NULL, quantity INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS order_events (
 id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
 status TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tickets (
 id INTEGER PRIMARY KEY, reference TEXT NOT NULL UNIQUE, user_id INTEGER REFERENCES users(id),
 name TEXT NOT NULL, email TEXT NOT NULL, subject TEXT NOT NULL, message TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'Open', response TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS subscribers (
 email TEXT PRIMARY KEY COLLATE NOCASE, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS auth_attempts (key TEXT NOT NULL, at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_auth_attempts ON auth_attempts(key, at);
CREATE INDEX IF NOT EXISTS idx_order_user ON orders(user_id,created_at);
"""

def initialize():
    db = connect()
    if uses_postgres():
        db.execute('SELECT pg_advisory_xact_lock(78123640)')
        schema = SCHEMA.replace('id INTEGER PRIMARY KEY', 'id SERIAL PRIMARY KEY')
        schema = schema.replace(' COLLATE NOCASE', '')
        db.executescript(schema)
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_user_email_lower ON users (LOWER(email))')
    else:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)
    if not db.execute("SELECT 1 FROM products LIMIT 1").fetchone():
        for p in PRODUCTS:
            db.execute("""INSERT INTO products(slug,name,category,price,compare_price,description,specs,image,color,badge,stock,featured,created_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (p['slug'],p['name'],p['category'],p['price'],p['compare_price'],p['description'],json.dumps(p['specs']),p['image'],p['color'],p['badge'],p['stock'],int(p['featured']),now()))
    demo_default = '0' if uses_postgres() else '1'
    if os.environ.get('NORTHSTAR_SEED_DEMO', demo_default) == '1' and not db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        db.execute("INSERT INTO users(name,email,password,phone,role,created_at) VALUES(?,?,?,?,?,?)", ("Alex Morgan","alex@northstar.local",password_hash("NorthStar123!"),"03001234567","customer",now()))
        db.execute("INSERT INTO users(name,email,password,role,created_at) VALUES(?,?,?,?,?)", ("NorthStar Admin","admin@northstar.local",password_hash("NorthStarAdmin123!"),"admin",now()))
        uid = db.execute("SELECT id FROM users WHERE email='alex@northstar.local'").fetchone()[0]
        db.execute("INSERT INTO addresses(user_id,label,name,phone,line1,line2,city,postal_code) VALUES(?,?,?,?,?,?,?,?)", (uid,"Home","Alex Morgan","03001234567","House 18, Street 4","Block 7, Gulshan-e-Iqbal","Karachi","75300"))
        db.execute("INSERT INTO wishlist(user_id,product_id,created_at) VALUES(?,?,?)",(uid,1,now()))
    admin_email = os.environ.get('NORTHSTAR_ADMIN_EMAIL', '').strip().lower()
    admin_password = os.environ.get('NORTHSTAR_ADMIN_PASSWORD', '')
    if admin_email and admin_password:
        if len(admin_password) < 16:
            raise RuntimeError('The bootstrap administrator password must be at least 16 characters.')
        if not db.execute('SELECT 1 FROM users WHERE email=?', (admin_email,)).fetchone():
            db.execute('INSERT INTO users(name,email,password,role,created_at) VALUES(?,?,?,?,?)',
                       ('NorthStar administrator', admin_email, password_hash(admin_password), 'admin', now()))
    db.commit()
    db.close()
