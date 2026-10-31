#!/usr/bin/env python3
"""NorthStar local application server. Run: python3 server.py

Uses only Python's standard library. The JSON API and SQLite database are real;
the bundled HTTP server is intended for local coursework and demonstration.
"""
import argparse
from datetime import datetime, timezone
from functools import wraps
import hashlib
import hmac
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import time
import traceback
from urllib.parse import parse_qs, unquote, urlparse

from catalog import CATEGORIES
from database import BASE, IntegrityError, connect, initialize, now, password_hash, password_matches

if sys.version_info < (3,10):
    raise SystemExit('NorthStar requires Python 3.10 or newer.')

ROUTES = []
SESSION_DAYS = 7
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
CITIES = ["Karachi", "Lahore", "Islamabad", "Rawalpindi", "Faisalabad", "Multan", "Peshawar", "Quetta", "Hyderabad", "Sialkot", "Gujranwala", "Bahawalpur", "Sukkur", "Abbottabad", "Other"]
COUPONS = {"WELCOME10": {"percent": 10, "minimum": 3000, "cap": 2000},
           "WORKSPACE15": {"percent": 15, "minimum": 10000, "cap": 3000}}

class APIError(Exception):
    def __init__(self, message, status=400, fields=None):
        self.message, self.status, self.fields = message, status, fields or {}

def route(method, path):
    def decorate(fn):
        ROUTES.append((method, re.compile("^" + path + "$"), fn))
        return fn
    return decorate

def login_required(fn):
    @wraps(fn)
    def decorated(r, **kwargs):
        if not r.user:
            raise APIError("Please sign in to continue.", 401)
        return fn(r, **kwargs)
    return decorated

def admin_required(fn):
    @wraps(fn)
    @login_required
    def decorated(r, **kwargs):
        if r.user['role'] != 'admin':
            raise APIError("This action is available to administrators only.", 403)
        return fn(r, **kwargs)
    return decorated

def text_value(data, key, minimum=0, maximum=255):
    value = data.get(key, "")
    if not isinstance(value, str):
        raise APIError("Please check the highlighted field.", fields={key: "Enter a valid value."})
    value = value.strip()
    if len(value) < minimum or len(value) > maximum:
        msg = "This field is required." if not value else f"Use between {minimum} and {maximum} characters."
        raise APIError("Please check the highlighted field.", fields={key: msg})
    return value

def email_value(data, key="email"):
    value = text_value(data,key,3,254).lower()
    if not EMAIL.fullmatch(value):
        raise APIError("Enter a valid email address.", fields={key:"Use an email such as name@example.com."})
    return value

def integer(data, key, minimum, maximum):
    value = data.get(key)
    if type(value) is not int or not minimum <= value <= maximum:
        raise APIError(f"Enter a whole number between {minimum:,} and {maximum:,}.", fields={key:"Enter a valid whole number."})
    return value

def valid_password(data, key="password"):
    value = data.get(key, "")
    if not isinstance(value, str) or len(value) < 8 or len(value) > 128 or not re.search(r"[A-Za-z]",value) or not re.search(r"\d",value):
        raise APIError("Use 8–128 characters including a letter and a number.", fields={key:"Use at least 8 characters, one letter and one number."})
    return value

def phone_value(data):
    value = text_value(data,"phone",10,20)
    digits = re.sub(r"[\s()+-]", "", value)
    if not re.fullmatch(r"(?:03\d{9}|923\d{9})",digits):
        raise APIError("Enter a valid Pakistani mobile number.", fields={"phone":"Use 03XXXXXXXXX or +923XXXXXXXXX."})
    return value

def address_value(data):
    city = text_value(data,"city",2,70)
    if city not in CITIES:
        raise APIError("Choose a delivery city.", fields={"city":"Choose a city from the list."})
    postal = text_value(data,"postal_code",5,5)
    if not re.fullmatch(r"\d{5}",postal):
        raise APIError("Enter a 5-digit postal code.", fields={"postal_code":"Use exactly 5 digits."})
    return dict(name=text_value(data,"name",2,80), phone=phone_value(data),
                line1=text_value(data,"line1",5,160), line2=text_value(data,"line2",0,160), city=city, postal_code=postal)

def public_user(row):
    return {key:row[key] for key in ("id","name","email","phone","role","created_at")} if row else None

def public_product(row):
    value = dict(row)
    value['specs'] = json.loads(value['specs'])
    value['featured'] = bool(value['featured'])
    value['active'] = bool(value['active'])
    return value

def product_or_404(r,pid, active=True):
    product = r.db.execute("SELECT * FROM products WHERE id=?" + (" AND active=1" if active else ""),(pid,)).fetchone()
    if not product:
        raise APIError("This product could not be found.",404)
    return product

def cart_summary(r):
    rows=r.db.execute("SELECT p.*,c.quantity FROM carts c JOIN products p ON p.id=c.product_id WHERE c.owner=? ORDER BY p.id",(r.owner,)).fetchall()
    items=[]
    for row in rows:
        p=public_product(row)
        p['line_total']=p['price']*p['quantity']
        items.append(p)
    subtotal=sum(p['line_total'] for p in items)
    coupon_row=r.db.execute("SELECT code FROM cart_coupons WHERE owner=?",(r.owner,)).fetchone()
    code=coupon_row['code'] if coupon_row else ""
    coupon=COUPONS.get(code)
    eligible=bool(coupon and subtotal >= coupon['minimum'])
    discount=min(subtotal*coupon['percent']//100,coupon['cap']) if eligible else 0
    shipping=0 if not items or subtotal-discount >= 8000 else 250
    return dict(items=items,count=sum(p['quantity'] for p in items),subtotal=subtotal,discount=discount,
                shipping=shipping,total=subtotal-discount+shipping,coupon=code,coupon_applied=eligible,
                coupon_message=(f"Spend Rs. {coupon['minimum']:,} before delivery to use {code}." if coupon and not eligible else ""),free_shipping_threshold=8000)

def merge_guest_cart(r,new_user):
    old_owner=r.owner
    new_owner=f"u:{new_user['id']}"
    if old_owner!=new_owner:
        for item in r.db.execute("SELECT c.*,p.stock FROM carts c JOIN products p ON p.id=c.product_id WHERE owner=?",(old_owner,)).fetchall():
            existing=r.db.execute("SELECT quantity FROM carts WHERE owner=? AND product_id=?",(new_owner,item['product_id'])).fetchone()
            qty=min(20,item['stock'],item['quantity']+(existing['quantity'] if existing else 0))
            if qty:
                r.db.execute("INSERT INTO carts VALUES(?,?,?) ON CONFLICT(owner,product_id) DO UPDATE SET quantity=excluded.quantity",(new_owner,item['product_id'],qty))
        r.db.execute("DELETE FROM carts WHERE owner=?",(old_owner,))
        promo=r.db.execute("SELECT code FROM cart_coupons WHERE owner=?",(old_owner,)).fetchone()
        if promo:
            r.db.execute("INSERT INTO cart_coupons VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET code=excluded.code",(new_owner,promo['code']))
        r.db.execute("DELETE FROM cart_coupons WHERE owner=?",(old_owner,))
    r.rotate_session(new_user)

@route("GET",r"/api/session")
def get_session(r):
    wishlist=[row[0] for row in r.db.execute("SELECT product_id FROM wishlist WHERE user_id=?",(r.user['id'],))] if r.user else []
    return {"user":public_user(r.user),"csrf_token":r.csrf,"cart_count":cart_summary(r)['count'],"wishlist":wishlist}

@route("GET",r"/api/config")
def config(r):
    return {"categories":CATEGORIES,"cities":CITIES,"currency":"PKR","delivery_fee":250,"free_shipping_threshold":8000}

@route("POST",r"/api/auth/register")
def register(r):
    name=text_value(r.data,'name',2,80)
    email=email_value(r.data)
    password=valid_password(r.data)
    if r.data.get('terms') is not True:
        raise APIError("Please accept the terms to create your account.",fields={"terms":"Accept the terms to continue."})
    try:
        cursor=r.db.execute("INSERT INTO users(name,email,password,created_at) VALUES(?,?,?,?)",(name,email,password_hash(password),now()))
    except IntegrityError:
        raise APIError("An account with this email already exists.",409,{"email":"Try signing in with this email."})
    user=r.db.execute("SELECT * FROM users WHERE id=?",(cursor.lastrowid,)).fetchone()
    merge_guest_cart(r,user)
    return {"user":public_user(user),"csrf_token":r.csrf},201

@route("POST",r"/api/auth/login")
def login(r):
    email=email_value(r.data)
    password=text_value(r.data,'password',1,128)
    key=r.client_ip+":"+email
    recent=r.db.execute("SELECT COUNT(*) FROM auth_attempts WHERE key=? AND at>?",(key,int(time.time())-900)).fetchone()[0]
    if recent>=8:
        raise APIError("Too many sign-in attempts. Please try again in 15 minutes.",429)
    user=r.db.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
    if not user or not password_matches(password,user['password']):
        r.db.execute("INSERT INTO auth_attempts VALUES(?,?)",(key,int(time.time())))
        r.db.commit()
        raise APIError("Your email or password is incorrect.",401)
    r.db.execute("DELETE FROM auth_attempts WHERE key=?",(key,))
    merge_guest_cart(r,user)
    return {"user":public_user(user),"csrf_token":r.csrf}

@route("POST",r"/api/auth/logout")
def logout(r):
    r.rotate_session(None)
    return {"message":"You have been signed out.","csrf_token":r.csrf}

@route("GET",r"/api/products")
def list_products(r):
    sql="SELECT * FROM products WHERE active=1"
    values=[]
    q=r.query.get('q','').strip()[:150]
    if q:
        sql+=" AND (instr(lower(name),lower(?))>0 OR instr(lower(description),lower(?))>0 OR instr(lower(category),lower(?))>0)"
        values += [q,q,q]
    category=r.query.get('category','')
    if category:
        sql+=" AND category=?"; values.append(category)
    if r.query.get('in_stock')=='1': sql+=" AND stock>0"
    if r.query.get('featured')=='1': sql+=" AND featured=1"
    if r.query.get('new')=='1': sql+=" AND badge='New arrival'"
    for key,operator in [('min_price','>='),('max_price','<=')]:
        if key in r.query:
            try: price=int(r.query[key])
            except ValueError: raise APIError("Price filters must be whole numbers.")
            sql+=f" AND price{operator}?"; values.append(price)
    sort={"featured":"featured DESC, id ASC","price_asc":"price ASC, id ASC","price_desc":"price DESC, id ASC","name":"name COLLATE NOCASE ASC","newest":"id DESC"}.get(r.query.get('sort','featured'),"featured DESC, id ASC")
    products=[public_product(row) for row in r.db.execute(sql+" ORDER BY "+sort,values)]
    return {"products":products,"total":len(products),"categories":CATEGORIES}

@route("GET",r"/api/products/(?P<slug>[a-z0-9-]+)")
def get_product(r,slug):
    row=r.db.execute("SELECT * FROM products WHERE (slug=? OR CAST(id AS TEXT)=?) AND active=1",(slug,slug)).fetchone()
    if not row: raise APIError("This product could not be found.",404)
    related=r.db.execute("SELECT * FROM products WHERE category=? AND id!=? AND active=1 LIMIT 4",(row['category'],row['id'])).fetchall()
    return {"product":public_product(row),"related":[public_product(x) for x in related]}

@route("GET",r"/api/cart")
def get_cart(r): return cart_summary(r)

@route("POST",r"/api/cart/items")
def add_cart(r):
    pid=integer(r.data,'product_id',1,2**31-1)
    qty=integer(r.data,'quantity',1,20)
    r.db.execute("BEGIN IMMEDIATE")
    p=product_or_404(r,pid)
    old=r.db.execute("SELECT quantity FROM carts WHERE owner=? AND product_id=?",(r.owner,pid)).fetchone()
    quantity=qty+(old['quantity'] if old else 0)
    if quantity>min(p['stock'],20):
        raise APIError("There is not enough stock for that quantity." if p['stock'] else "This item is currently out of stock.",409)
    r.db.execute("INSERT INTO carts VALUES(?,?,?) ON CONFLICT(owner,product_id) DO UPDATE SET quantity=excluded.quantity",(r.owner,pid,quantity))
    return cart_summary(r),201

@route("PATCH",r"/api/cart/items/(?P<pid>\d+)")
def update_cart(r,pid):
    qty=integer(r.data,'quantity',1,20)
    r.db.execute("BEGIN IMMEDIATE")
    p=product_or_404(r,int(pid))
    if qty>p['stock']: raise APIError("There is not enough stock for that quantity.",409)
    cursor=r.db.execute("UPDATE carts SET quantity=? WHERE owner=? AND product_id=?",(qty,r.owner,int(pid)))
    if not cursor.rowcount: raise APIError("This item is not in your cart.",404)
    return cart_summary(r)

@route("DELETE",r"/api/cart/items/(?P<pid>\d+)")
def delete_cart(r,pid):
    result=r.db.execute("DELETE FROM carts WHERE owner=? AND product_id=?",(r.owner,int(pid)))
    if not result.rowcount: raise APIError("This item is not in your cart.",404)
    return cart_summary(r)

@route("POST",r"/api/cart/coupon")
def apply_coupon(r):
    code=text_value(r.data,'code',1,30).upper()
    if code not in COUPONS: raise APIError("That promo code is not valid.",fields={"code":"Try WELCOME10 on orders of Rs. 3,000 or more."})
    if cart_summary(r)['subtotal']<COUPONS[code]['minimum']:
        raise APIError(f"{code} requires a subtotal of Rs. {COUPONS[code]['minimum']:,}.")
    r.db.execute("INSERT INTO cart_coupons VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET code=excluded.code",(r.owner,code))
    return cart_summary(r)

@route("DELETE",r"/api/cart/coupon")
def delete_coupon(r):
    r.db.execute("DELETE FROM cart_coupons WHERE owner=?",(r.owner,))
    return cart_summary(r)

@route("GET",r"/api/wishlist")
@login_required
def get_wishlist(r):
    rows=r.db.execute("SELECT p.* FROM wishlist w JOIN products p ON p.id=w.product_id WHERE user_id=? AND active=1 ORDER BY w.created_at DESC",(r.user['id'],)).fetchall()
    return {"products":[public_product(x) for x in rows]}

@route("POST",r"/api/wishlist")
@login_required
def add_wishlist(r):
    pid=integer(r.data,'product_id',1,2**31-1)
    product_or_404(r,pid)
    r.db.execute("INSERT OR IGNORE INTO wishlist VALUES(?,?,?)",(r.user['id'],pid,now()))
    return {"message":"Saved to your wishlist.","product_id":pid},201

@route("DELETE",r"/api/wishlist/(?P<pid>\d+)")
@login_required
def delete_wishlist(r,pid):
    cursor=r.db.execute("DELETE FROM wishlist WHERE user_id=? AND product_id=?",(r.user['id'],int(pid)))
    if not cursor.rowcount: raise APIError("This item is not in your wishlist.",404)
    return {"message":"Removed from your wishlist."}

@route("GET",r"/api/addresses")
@login_required
def addresses(r):
    return {"addresses":[dict(x) for x in r.db.execute("SELECT * FROM addresses WHERE user_id=? ORDER BY id",(r.user['id'],))]}

@route("POST",r"/api/addresses")
@login_required
def add_address(r):
    value=address_value(r.data)
    label=text_value(r.data,'label',1,40)
    if r.db.execute("SELECT COUNT(*) FROM addresses WHERE user_id=?",(r.user['id'],)).fetchone()[0]>=10:
        raise APIError("You can save up to 10 addresses.")
    cursor=r.db.execute("INSERT INTO addresses(user_id,label,name,phone,line1,line2,city,postal_code) VALUES(?,?,?,?,?,?,?,?)",(r.user['id'],label,*value.values()))
    return {"address":dict(r.db.execute("SELECT * FROM addresses WHERE id=?",(cursor.lastrowid,)).fetchone())},201

@route("PATCH",r"/api/addresses/(?P<aid>\d+)")
@login_required
def edit_address(r,aid):
    value=address_value(r.data)
    label=text_value(r.data,'label',1,40)
    cursor=r.db.execute("UPDATE addresses SET label=?,name=?,phone=?,line1=?,line2=?,city=?,postal_code=? WHERE id=? AND user_id=?",(label,*value.values(),int(aid),r.user['id']))
    if not cursor.rowcount: raise APIError("That address could not be found.",404)
    return {"address":dict(r.db.execute("SELECT * FROM addresses WHERE id=?",(int(aid),)).fetchone())}

@route("DELETE",r"/api/addresses/(?P<aid>\d+)")
@login_required
def remove_address(r,aid):
    cursor=r.db.execute("DELETE FROM addresses WHERE id=? AND user_id=?",(int(aid),r.user['id']))
    if not cursor.rowcount: raise APIError("That address could not be found.",404)
    return {"message":"Address removed."}

@route("PATCH",r"/api/profile")
@login_required
def profile(r):
    name=text_value(r.data,'name',2,80)
    phone=phone_value(r.data) if r.data.get('phone') else ''
    r.db.execute("UPDATE users SET name=?,phone=? WHERE id=?",(name,phone,r.user['id']))
    r.user=r.db.execute("SELECT * FROM users WHERE id=?",(r.user['id'],)).fetchone()
    return {"user":public_user(r.user)}

@route("POST",r"/api/profile/password")
@login_required
def change_password(r):
    old=text_value(r.data,'current_password',1,128)
    if not password_matches(old,r.user['password']): raise APIError("Your current password is incorrect.",fields={"current_password":"Check your current password."})
    new=valid_password(r.data,'new_password')
    r.db.execute("UPDATE users SET password=? WHERE id=?",(password_hash(new),r.user['id']))
    r.db.execute("DELETE FROM sessions WHERE user_id=? AND id!=?",(r.user['id'],r.sid))
    return {"message":"Password updated. Other sessions have been signed out."}

def order_value(r,row):
    value=dict(row)
    value['address']=json.loads(value['address'])
    value['items']=[dict(x) for x in r.db.execute("SELECT * FROM order_items WHERE order_id=?",(value['id'],))]
    value['events']=[dict(x) for x in r.db.execute("SELECT * FROM order_events WHERE order_id=? ORDER BY id",(value['id'],))]
    value.pop('idempotency_key',None)
    return value

@route("POST",r"/api/orders")
@login_required
def place_order(r):
    key=text_value(r.data,'idempotency_key',16,100)
    r.db.execute("BEGIN IMMEDIATE")
    old=r.db.execute("SELECT * FROM orders WHERE user_id=? AND idempotency_key=?",(r.user['id'],key)).fetchone()
    if old: return {"order":order_value(r,old)}
    if r.data.get('payment_method')!='cod': raise APIError("Choose cash on delivery.",fields={"payment_method":"Only cash on delivery is supported."})
    if r.data.get('terms') is not True: raise APIError("Please accept the order terms to continue.",fields={"terms":"Accept the order terms."})
    data=r.data.get('address')
    if not isinstance(data,dict): raise APIError("Enter a delivery address.")
    address=address_value(data)
    note=text_value(r.data,'note',0,500)
    cart=cart_summary(r)
    if not cart['items']: raise APIError("Your cart is empty. Add something before checking out.",409)
    for p in cart['items']:
        if not p['active'] or p['quantity']>p['stock']:
            raise APIError(f"{p['name']} is no longer available in the requested quantity. Update your cart.",409)
    number="NS-"+datetime.now(timezone.utc).strftime('%y%m%d')+"-"+secrets.token_hex(3).upper()
    cursor=r.db.execute("INSERT INTO orders(number,user_id,status,subtotal,discount,shipping,total,coupon,address,payment_method,note,created_at,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(number,r.user['id'],'Confirmed',cart['subtotal'],cart['discount'],cart['shipping'],cart['total'],cart['coupon'] if cart['coupon_applied'] else '',json.dumps(address),'cod',note,now(),key))
    oid=cursor.lastrowid
    for p in cart['items']:
        changed=r.db.execute("UPDATE products SET stock=stock-? WHERE id=? AND stock>=? AND active=1",(p['quantity'],p['id'],p['quantity']))
        if changed.rowcount!=1: raise APIError("An item has just sold out. Please refresh your cart.",409)
        r.db.execute("INSERT INTO order_items(order_id,product_id,name,image,price,quantity) VALUES(?,?,?,?,?,?)",(oid,p['id'],p['name'],p['image'],p['price'],p['quantity']))
    r.db.execute("INSERT INTO order_events(order_id,status,note,created_at) VALUES(?,?,?,?)",(oid,'Confirmed','Order received. Payment is due on delivery.',now()))
    r.db.execute("DELETE FROM carts WHERE owner=?",(r.owner,))
    r.db.execute("DELETE FROM cart_coupons WHERE owner=?",(r.owner,))
    return {"order":order_value(r,r.db.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone())},201

@route("GET",r"/api/orders")
@login_required
def orders(r):
    return {"orders":[order_value(r,row) for row in r.db.execute("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC",(r.user['id'],)).fetchall()]}

@route("GET",r"/api/orders/(?P<number>NS-[A-Z0-9-]+)")
@login_required
def get_order(r,number):
    row=r.db.execute("SELECT * FROM orders WHERE number=? AND user_id=?",(number,r.user['id'])).fetchone()
    if not row: raise APIError("That order could not be found.",404)
    return {"order":order_value(r,row)}

def transition_order(r,row,status):
    allowed={'Confirmed':['Processing','Cancelled'],'Processing':['Shipped','Cancelled'],'Shipped':['Delivered'],'Delivered':[],'Cancelled':[]}
    if status not in allowed[row['status']]: raise APIError(f"An order cannot move from {row['status']} to {status}.",409)
    if status=='Cancelled':
        for p in r.db.execute("SELECT * FROM order_items WHERE order_id=?",(row['id'],)).fetchall():
            r.db.execute("UPDATE products SET stock=stock+? WHERE id=?",(p['quantity'],p['product_id']))
    r.db.execute("UPDATE orders SET status=? WHERE id=?",(status,row['id']))
    messages={'Processing':'Your order is being prepared.','Shipped':'Your order is on its way. Estimated delivery: 3–5 business days.','Delivered':'Your order has arrived. Thank you for shopping with NorthStar.','Cancelled':'Order cancelled. Reserved stock has been restored.'}
    r.db.execute("INSERT INTO order_events(order_id,status,note,created_at) VALUES(?,?,?,?)",(row['id'],status,messages[status],now()))

@route("POST",r"/api/orders/(?P<number>NS-[A-Z0-9-]+)/cancel")
@login_required
def cancel_order(r,number):
    r.db.execute("BEGIN IMMEDIATE")
    row=r.db.execute("SELECT * FROM orders WHERE number=? AND user_id=?",(number,r.user['id'])).fetchone()
    if not row: raise APIError("That order could not be found.",404)
    if row['status'] not in ('Confirmed','Processing'): raise APIError("Only orders that have not shipped can be cancelled.",409)
    transition_order(r,row,'Cancelled')
    return {"order":order_value(r,r.db.execute("SELECT * FROM orders WHERE id=?",(row['id'],)).fetchone())}

@route("POST",r"/api/support")
def contact(r):
    name=text_value(r.data,'name',2,80)
    email=email_value(r.data)
    subject=text_value(r.data,'subject',3,120)
    message=text_value(r.data,'message',20,3000)
    key='support:'+r.client_ip
    if r.db.execute("SELECT COUNT(*) FROM auth_attempts WHERE key=? AND at>?",(key,int(time.time())-3600)).fetchone()[0]>=10:
        raise APIError("You have sent several messages. Please try again in an hour.",429)
    reference="NSH-"+secrets.token_hex(4).upper()
    r.db.execute("INSERT INTO tickets(reference,user_id,name,email,subject,message,created_at) VALUES(?,?,?,?,?,?,?)",(reference,r.user['id'] if r.user else None,name,email,subject,message,now()))
    r.db.execute("INSERT INTO auth_attempts VALUES(?,?)",(key,int(time.time())))
    return {"message":"Your message has been received.","reference":reference},201

@route("GET",r"/api/support")
@login_required
def my_tickets(r):
    return {"tickets":[dict(x) for x in r.db.execute("SELECT * FROM tickets WHERE user_id=? ORDER BY id DESC",(r.user['id'],))]}

@route("POST",r"/api/newsletter")
def newsletter(r):
    email=email_value(r.data)
    r.db.execute("INSERT OR IGNORE INTO subscribers VALUES(?,?)",(email,now()))
    return {"message":"You are on the list. Welcome to the NorthStar edit."},201

@route("GET",r"/api/admin/overview")
@admin_required
def admin_overview(r):
    stats={"revenue":r.db.execute("SELECT COALESCE(SUM(total),0) FROM orders WHERE status='Delivered'").fetchone()[0],
           "orders":r.db.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
           "customers":r.db.execute("SELECT COUNT(*) FROM users WHERE role='customer'").fetchone()[0],
           "low_stock":r.db.execute("SELECT COUNT(*) FROM products WHERE active=1 AND stock<5").fetchone()[0],
           "open_tickets":r.db.execute("SELECT COUNT(*) FROM tickets WHERE status='Open'").fetchone()[0]}
    return {"stats":stats}

@route("GET",r"/api/admin/products")
@admin_required
def admin_products(r): return {"products":[public_product(x) for x in r.db.execute("SELECT * FROM products ORDER BY id DESC")]}

def product_data(r):
    data=r.data
    name=text_value(data,'name',2,100)
    slug=text_value(data,'slug',2,100)
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*",slug): raise APIError("Use a lowercase slug with hyphens.",fields={"slug":"Example: halo-desk-lamp"})
    category=text_value(data,'category',1,30)
    if category not in CATEGORIES: raise APIError("Choose a valid category.")
    price=integer(data,'price',1,10000000)
    stock=integer(data,'stock',0,100000)
    description=text_value(data,'description',20,3000)
    image=text_value(data,'image',1,255)
    if not image.startswith('/static/images/') or '..' in image or not (BASE/image.lstrip('/')).is_file():
        raise APIError("Choose an image from the bundled catalogue.")
    color=text_value(data,'color',7,7)
    if not re.fullmatch(r"#[0-9a-fA-F]{6}",color): raise APIError("Use a hex colour such as #677361.")
    badge=text_value(data,'badge',0,30)
    compare=data.get('compare_price')
    if compare is not None and (type(compare) is not int or compare<=price or compare>10000000): raise APIError("The original price must be greater than the selling price.")
    specs=data.get('specs',{})
    if not isinstance(specs,dict) or len(specs)>10 or any(not isinstance(k,str) or not isinstance(v,str) or len(k)>60 or len(v)>200 for k,v in specs.items()): raise APIError("Specifications must be a small text-to-text object.")
    return (slug,name,category,price,compare,description,json.dumps(specs),image,color,badge,stock,int(data.get('featured') is True),int(data.get('active',True) is True))

@route("POST",r"/api/admin/products")
@admin_required
def create_product(r):
    value=product_data(r)
    try:
        cursor=r.db.execute("INSERT INTO products(slug,name,category,price,compare_price,description,specs,image,color,badge,stock,featured,active,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(*value,now()))
    except IntegrityError: raise APIError("A product with that slug already exists.",409)
    return {"product":public_product(product_or_404(r,cursor.lastrowid,False))},201

@route("PATCH",r"/api/admin/products/(?P<pid>\d+)")
@admin_required
def admin_edit_product(r,pid):
    current=public_product(product_or_404(r,int(pid),False))
    current.update(r.data);r.data=current
    value=product_data(r)
    try:
        r.db.execute("UPDATE products SET slug=?,name=?,category=?,price=?,compare_price=?,description=?,specs=?,image=?,color=?,badge=?,stock=?,featured=?,active=? WHERE id=?",(*value,int(pid)))
    except IntegrityError: raise APIError("A product with that slug already exists.",409)
    return {"product":public_product(product_or_404(r,int(pid),False))}

@route("DELETE",r"/api/admin/products/(?P<pid>\d+)")
@admin_required
def archive_product(r,pid):
    product_or_404(r,int(pid),False)
    r.db.execute("UPDATE products SET active=0 WHERE id=?",(int(pid),))
    r.db.execute("DELETE FROM carts WHERE product_id=?",(int(pid),))
    return {"message":"Product archived. Existing order history is preserved."}

@route("GET",r"/api/admin/orders")
@admin_required
def admin_orders(r):
    rows=r.db.execute("SELECT o.*,u.name AS customer_name,u.email AS customer_email FROM orders o JOIN users u ON u.id=o.user_id ORDER BY o.id DESC").fetchall()
    return {"orders":[order_value(r,x) for x in rows]}

@route("PATCH",r"/api/admin/orders/(?P<number>NS-[A-Z0-9-]+)")
@admin_required
def admin_order_status(r,number):
    status=text_value(r.data,'status',1,30)
    r.db.execute("BEGIN IMMEDIATE")
    row=r.db.execute("SELECT * FROM orders WHERE number=?",(number,)).fetchone()
    if not row: raise APIError("That order could not be found.",404)
    transition_order(r,row,status)
    return {"order":order_value(r,r.db.execute("SELECT * FROM orders WHERE number=?",(number,)).fetchone())}

@route("GET",r"/api/admin/tickets")
@admin_required
def admin_tickets(r): return {"tickets":[dict(x) for x in r.db.execute("SELECT * FROM tickets ORDER BY id DESC")]}

@route("PATCH",r"/api/admin/tickets/(?P<tid>\d+)")
@admin_required
def respond_ticket(r,tid):
    response=text_value(r.data,'response',5,3000)
    status=text_value(r.data,'status',1,30)
    if status not in ('Open','Resolved'): raise APIError("Choose Open or Resolved.")
    cursor=r.db.execute("UPDATE tickets SET response=?,status=? WHERE id=?",(response,status,int(tid)))
    if not cursor.rowcount: raise APIError("That support request could not be found.",404)
    return {"message":"Support response saved."}

class Request:
    def __init__(self, handler, db):
        self.handler,self.db=handler,db
        self.data={}
        parsed=urlparse(handler.path)
        self.path=unquote(parsed.path)
        self.query={key:values[-1] for key,values in parse_qs(parsed.query).items()}
        self.client_ip=handler.client_address[0]
        if os.environ.get("NORTHSTAR_TRUST_PROXY") == "1":
            forwarded=handler.headers.get("X-Forwarded-For", "")
            if forwarded:
                self.client_ip=forwarded.split(",")[-1].strip()[:64]
        cookie=SimpleCookie()
        try: cookie.load(handler.headers.get('Cookie',''))
        except Exception: pass
        token=cookie.get('northstar_session')
        self.sid=hashlib.sha256(token.value.encode()).hexdigest() if token else ''
        row=db.execute("SELECT * FROM sessions WHERE id=? AND expires>?",(self.sid,int(time.time()))).fetchone()
        self.new_cookie=None
        self.user=db.execute("SELECT * FROM users WHERE id=?",(row['user_id'],)).fetchone() if row and row['user_id'] else None
        if row: self.csrf=row['csrf']
        else: self.rotate_session(None)
        self.owner=f"u:{self.user['id']}" if self.user else "g:"+self.sid
        # Commit session creation before routes open explicit write transactions.
        db.commit()

    def rotate_session(self,user):
        old_sid=getattr(self,'sid','')
        if old_sid: self.db.execute("DELETE FROM sessions WHERE id=?",(old_sid,))
        token=secrets.token_urlsafe(32)
        self.sid=hashlib.sha256(token.encode()).hexdigest()
        self.csrf=secrets.token_urlsafe(32)
        self.user=user
        self.new_cookie=token
        self.owner=f"u:{user['id']}" if user else 'g:'+self.sid
        self.db.execute("INSERT INTO sessions VALUES(?,?,?,?)",(self.sid,user['id'] if user else None,self.csrf,int(time.time())+SESSION_DAYS*86400))
        self.db.execute("DELETE FROM sessions WHERE expires<?",(int(time.time()),))

class Handler(BaseHTTPRequestHandler):
    server_version="NorthStar/1.0"
    def do_GET(self): self.dispatch()
    def do_HEAD(self): self.dispatch()
    def do_POST(self): self.dispatch()
    def do_PATCH(self): self.dispatch()
    def do_DELETE(self): self.dispatch()
    def do_PUT(self): self.dispatch()

    def send_body(self,body,status=200,content_type='application/json; charset=utf-8',cookie=None,cache=False):
        if isinstance(body,(dict,list)): body=json.dumps(body,ensure_ascii=False).encode('utf-8')
        elif isinstance(body,str): body=body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','same-origin')
        self.send_header('Permissions-Policy','camera=(), microphone=(), geolocation=()')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")
        self.send_header('Cache-Control','public, max-age=3600' if cache else 'no-store')
        if cookie:
            secure='; Secure' if os.environ.get('NORTHSTAR_SECURE_COOKIE')=='1' else ''
            self.send_header('Set-Cookie',f'northstar_session={cookie}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_DAYS*86400}{secure}')
        self.end_headers()
        if self.command!='HEAD':
            try: self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError): pass

    def dispatch(self):
        path=unquote(urlparse(self.path).path)
        if path.startswith('/static/'):
            target=(BASE/path.lstrip('/')).resolve()
            if self.command not in ('GET','HEAD'):
                return self.send_body({'error':{'message':'Method not allowed.'}},405)
            if not target.is_relative_to((BASE/'static').resolve()) or not target.is_file():
                return self.send_body({'error':{'message':'File not found.'}},404)
            return self.send_body(target.read_bytes(),content_type=mimetypes.guess_type(str(target))[0] or 'application/octet-stream',cache=True)
        if path=='/favicon.ico':
            return self.send_body((BASE/'static/images/brand.svg').read_bytes(),content_type='image/svg+xml',cache=True)
        if not path.startswith('/api/'):
            if self.command not in ('GET','HEAD'): return self.send_body({'error':{'message':'Method not allowed.'}},405)
            known=bool(re.fullmatch(r'/(?:shop|wishlist|cart|checkout|login|register|account|orders(?:/NS-[A-Z0-9-]+)?|support|about|journal|privacy|terms|shipping|admin(?:/(?:products|orders|support))?|product/[a-z0-9-]+)?/?',path))
            if known and path.startswith('/product/'):
                check=connect()
                try:
                    known=bool(check.execute('SELECT 1 FROM products WHERE slug=? AND active=1',(path.strip('/').split('/')[1],)).fetchone())
                finally: check.close()
            return self.send_body((BASE/'templates/index.html').read_bytes(),200 if known else 404,'text/html; charset=utf-8')
        db=connect()
        r=None
        try:
            r=Request(self,db)
            if self.command not in ('GET','HEAD'):
                token=self.headers.get('X-CSRF-Token','')
                if not token or not hmac.compare_digest(token,r.csrf): raise APIError("Your session has expired. Refresh the page and try again.",403)
                origin=self.headers.get('Origin')
                if origin and urlparse(origin).netloc != self.headers.get('Host'): raise APIError("Cross-origin requests are not allowed.",403)
                content_type=self.headers.get('Content-Type','').split(';')[0]
                try: length=int(self.headers.get('Content-Length','0'))
                except ValueError: raise APIError("Invalid request length.")
                if length<0 or length>65536: raise APIError("Request body is too large.",413)
                if length:
                    if content_type!='application/json': raise APIError("Send a JSON request body.",415)
                    try: r.data=json.loads(self.rfile.read(length))
                    except (ValueError,UnicodeDecodeError): raise APIError("The request body is not valid JSON.")
                    if not isinstance(r.data,dict): raise APIError("Send a JSON object.")
            method='GET' if self.command=='HEAD' else self.command
            for verb,pattern,fn in ROUTES:
                match=pattern.fullmatch(r.path)
                if verb==method and match:
                    result=fn(r,**match.groupdict())
                    body,status=result if isinstance(result,tuple) else (result,200)
                    db.commit()
                    return self.send_body(body,status,cookie=r.new_cookie)
            exists=any(pattern.fullmatch(r.path) for _,pattern,_ in ROUTES)
            raise APIError("Method not allowed." if exists else "This API resource could not be found.",405 if exists else 404)
        except APIError as exc:
            db.rollback()
            self.send_body({'error':{'message':exc.message,'fields':exc.fields}},exc.status,cookie=r.new_cookie if r else None)
        except Exception:
            db.rollback()
            traceback.print_exc()
            self.send_body({'error':{'message':'Something went wrong. Please try again.','fields':{}}},500)
        finally: db.close()

    def log_message(self,format,*args):
        safe=re.sub(r'[\x00-\x1f\x7f]','',str(args[0])) if args else ''
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {self.command} {safe}",flush=True)

def main():
    parser=argparse.ArgumentParser(description='Run NorthStar locally. Python 3.10 or newer; no pip installation needed.')
    parser.add_argument('--host',default=os.environ.get('HOST','127.0.0.1'))
    parser.add_argument('--port',type=int,default=int(os.environ.get('PORT','8000')))
    parser.add_argument('--strictPort',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    initialize()
    server=ThreadingHTTPServer((args.host,args.port),Handler)
    server.daemon_threads=True
    print(f"\n  NORTHSTAR\n  Local: http://{args.host}:{args.port}\n  Press Ctrl+C to stop.\n",flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: print('\nNorthStar stopped.')
    finally: server.server_close()

if __name__=='__main__': main()
