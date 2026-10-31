/* NorthStar storefront. Native browser APIs only; no build step or remote CDN. */
'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const e = escapeHTML;
const money = value => `Rs. ${Number(value || 0).toLocaleString('en-PK')}`;
const date = value => new Intl.DateTimeFormat('en-GB', {day:'numeric', month:'short', year:'numeric'}).format(new Date(value));
const paths = {
 search:'<circle cx="10.8" cy="10.8" r="6.7"/><path d="m16 16 4.5 4.5"/>',
 heart:'<path d="M20.8 4.7a5.2 5.2 0 0 0-7.4 0L12 6.1l-1.4-1.4a5.2 5.2 0 0 0-7.4 7.4L12 21l8.8-8.9a5.2 5.2 0 0 0 0-7.4Z"/>',
 user:'<circle cx="12" cy="7.5" r="3.5"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
 bag:'<path d="M5 7h14l1 14H4L5 7Z"/><path d="M8 8V6a4 4 0 0 1 8 0v2"/>',
 menu:'<path d="M3 6h18M3 12h18M3 18h18"/>',
 arrow:'<path d="M5 19 19 5M5 5h14v14"/>',
 plus:'<path d="M12 4v16M4 12h16"/>',
 truck:'<path d="M2 5h12v12H2zM14 9h4l4 5v3h-8"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="18" r="2"/>',
 return:'<path d="M4 10a8 8 0 1 1 0 6M4 4v6h6"/>',
 leaf:'<path d="M20 3C7 1 1 10 7 17s15-1 13-14Z"/><path d="m3 21 12-12"/>',
 shield:'<path d="m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6l8-4Z"/><path d="m8 12 3 3 5-6"/>',
 box:'<path d="m3 7 9-5 9 5v11l-9 5-9-5V7Zm0 0 9 5 9-5M12 12v11M7 4.5l9 5"/>',
 pin:'<path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/>',
 help:'<circle cx="12" cy="12" r="9"/><path d="M9 9a3 3 0 1 1 4 3c-1 .4-1 1-1 2M12 17v.5"/>',
 settings:'<path d="M3 6h18M3 12h18M3 18h18"/><circle cx="8" cy="6" r="2" fill="currentColor"/><circle cx="16" cy="12" r="2" fill="currentColor"/><circle cx="10" cy="18" r="2" fill="currentColor"/>',
 logout:'<path d="M10 3H4v18h6M9 12h12m-5-5 5 5-5 5"/>',
 eye:'<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
 check:'<path d="m5 12 4 4L19 6"/>',
 mail:'<rect x="2" y="5" width="20" height="14" rx="1"/><path d="m2 6 10 7 10-7"/>'
};
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.box}</svg>`;
const state = {user:null, csrf:'', wishlist:[], cartCount:0, config:{categories:[],cities:[]}, products:new Map(), addresses:[], adminProducts:[], adminOrders:[], tickets:[], sessionReady:false};
let renderNumber = 0;
let retryAction = null;
let checkoutKey = '';

class RequestError extends Error {
 constructor(message, status=0, fields={}) { super(message); this.status=status; this.fields=fields; }
}
async function api(url, options={}) {
 const controller = new AbortController();
 const timer = setTimeout(() => controller.abort(), 15000);
 const headers = {'Accept':'application/json', ...(options.method && options.method !== 'GET' ? {'Content-Type':'application/json','X-CSRF-Token':state.csrf} : {})};
 try {
  const response = await fetch(url, {...options, headers:{...headers,...options.headers}, signal:controller.signal, credentials:'same-origin', cache:'no-store', body:options.body === undefined ? undefined : JSON.stringify(options.body)});
  let data;
  try { data = await response.json(); } catch { throw new RequestError('The server sent an unexpected response. Please try again.', response.status); }
  if (!response.ok) throw new RequestError(data.error?.message || 'Something went wrong. Please try again.',response.status,data.error?.fields || {});
  if (data.csrf_token) state.csrf = data.csrf_token;
  return data;
 } catch (err) {
  if (err instanceof RequestError) throw err;
  throw new RequestError(err.name === 'AbortError' ? 'The request took too long. Please try again.' : 'We couldn’t reach NorthStar. Check your connection and try again.');
 } finally { clearTimeout(timer); }
}
function remember(products) { products.forEach(p => state.products.set(p.id, p)); return products; }
function updateHeader() {
 $('#cart-count').textContent = state.cartCount;
 $('#bag-link').setAttribute('aria-label',`Shopping bag, ${state.cartCount} items`);
 $('#account-link').href = state.user ? '/account' : '/login';
 $('#account-link').setAttribute('aria-label',state.user ? `Account: ${state.user.name}` : 'Sign in');
 $$('.desktop-nav a').forEach(a=>a.classList.toggle('active', a.pathname === location.pathname && (!a.search || a.search === location.search)));
}
async function refreshSession() {
 const data = await api('/api/session');
 state.user=data.user; state.wishlist=data.wishlist; state.cartCount=data.cart_count; state.sessionReady=true; updateHeader();
}
function toast(message, error=false, link='') {
 const node=document.createElement('div');node.className=`toast${error?' error':''}`;
 node.innerHTML=`<span>${e(message)}</span>${link ? `<a href="${e(link)}" data-link>View bag</a>` : ''}<button aria-label="Dismiss notification">✕</button>`;
 node.lastElementChild.addEventListener('click',()=>node.remove());$('#toasts').append(node);
 setTimeout(()=>node.remove(),7000);
}
function closePanels() {
 $('#search-panel').hidden=true;$('#search-toggle').setAttribute('aria-expanded','false');
 $('#mobile-nav').hidden=true;$('#menu-toggle').setAttribute('aria-expanded','false');
}
function navigate(url, {replace=false, scroll=true}={}) {
 const target = new URL(url,location.origin);
 if (target.origin !== location.origin) return;
 history[replace?'replaceState':'pushState']({},'',target.pathname+target.search+target.hash);
 closePanels(); if ($('#modal').open) $('#modal').close();
 return renderRoute(scroll);
}
function mount(html, n, {focus=true}={}) {
 if (n !== renderNumber) return false;
 $('#main').innerHTML = html;
 $('#main').removeAttribute('aria-busy');
 if (focus) $('#main').focus({preventScroll:true});
 return true;
}
function empty(title, message, {symbol='bag',url='/shop',label='Explore the collection',action=''}={}) {
 return `<div class="empty-state"><div class="empty-icon">${icon(symbol)}</div><h2>${e(title)}</h2><p>${e(message)}</p>${action ? `<button class="btn btn-dark" data-action="${e(action)}">${e(label)}</button>` : url ? `<a class="btn btn-dark" href="${e(url)}" data-link>${e(label)} ${icon('arrow')}</a>`:''}</div>`;
}
const crumb = (name, parent='') => `<div class="breadcrumb"><a href="/" data-link>Home</a><span>/</span>${parent?`<a href="/shop" data-link>Shop</a><span>/</span>`:''}<span>${e(name)}</span></div>`;
const heading = (title, subtitle='', eyebrow='THE NORTHSTAR EDIT') => `<div class="page-heading"><p class="eyebrow">${e(eyebrow)}</p><h1>${e(title)}</h1>${subtitle?`<p>${e(subtitle)}</p>`:''}</div>`;
const status = s => `<span class="status ${e(s)}">${e(s)}</span>`;
const errorBox = () => '<div class="form-error" role="alert" hidden></div>';
function field(name, label, value='', {type='text', required=true, placeholder='', min='', max='', autocomplete='', hint='', pattern='', readonly=false}={}) {
 const id=`field-${name}-${Math.random().toString(36).slice(2,7)}`;
 return `<div class="field"><label for="${id}">${label}${required?'':' <span class="optional">(optional)</span>'}</label><div class="${type==='password'?'password-field':''}"><input id="${id}" name="${e(name)}" type="${type}" value="${e(value)}" ${required?'required':''} ${placeholder?`placeholder="${e(placeholder)}"`:''} ${min?`minlength="${min}"`:''} ${max?`maxlength="${max}"`:''} ${autocomplete?`autocomplete="${autocomplete}"`:''} ${pattern?`pattern="${e(pattern)}"`:''} ${readonly?'readonly':''}>${type==='password'?`<button type="button" data-action="show-password" aria-label="Show password">${icon('eye')}</button>`:''}</div>${hint?`<p class="fineprint">${e(hint)}</p>`:''}</div>`;
}
function selectField(name,label,options,value='',required=true) {
 return `<div class="field"><label for="select-${e(name)}">${label}</label><select id="select-${e(name)}" name="${e(name)}" ${required?'required':''}><option value="">Select ${e(label.toLowerCase())}</option>${options.map(o=>`<option value="${e(o)}" ${o===value?'selected':''}>${e(o)}</option>`).join('')}</select></div>`;
}
function productCard(p) {
 const saved=state.wishlist.includes(p.id);
 return `<article class="product-card" data-product-id="${p.id}"><div class="product-visual"><a href="/product/${e(p.slug)}" data-link aria-label="View ${e(p.name)}"><img src="${e(p.image)}" alt="${e(p.name)}" loading="lazy" width="600" height="600"></a>${!p.stock?'<span class="product-badge sold">Out of stock</span>':p.badge?`<span class="product-badge">${e(p.badge)}</span>`:''}<button class="heart-btn ${saved?'is-saved':''}" data-action="save" data-id="${p.id}" aria-label="${saved?'Remove':'Save'} ${e(p.name)} ${saved?'from':'to'} wishlist" aria-pressed="${saved}">${icon('heart')}</button><button class="quick-add" data-action="add" data-id="${p.id}" ${!p.stock?'disabled':''} aria-label="Add ${e(p.name)} to bag"><span>${p.stock?'Add to bag':'Back soon'}</span>${icon('plus')}</button></div><div class="product-meta"><div><h3><a href="/product/${e(p.slug)}" data-link>${e(p.name)}</a></h3><p>${e(p.category)}</p></div><div class="price">${money(p.price)}${p.compare_price?`<del class="compare">${money(p.compare_price)}</del>`:''}</div></div></article>`;
}
const productGrid = products => `<div class="product-grid">${products.map(productCard).join('')}</div>`;
function journalCards() {
 return `<div class="journal-grid">${[
  {tag:'SPACES · 4 MIN READ',title:'A calmer desk. A clearer mind.',image:'/static/images/workspace-hero.png'},
  {tag:'RITUALS · 3 MIN READ',title:'The art of a slower morning.',image:'/static/images/workspace-hero.png'},
  {tag:'ON THE MOVE · 3 MIN READ',title:'Carry less. Make room for more.',image:'/static/images/roam-canvas-tote.svg'}
 ].map((j,i)=>`<article class="journal-card"><div class="journal-art"><img src="${j.image}" alt="${e(j.title)}" loading="lazy"></div><p class="eyebrow">${j.tag}</p><h3>${j.title}</h3><button class="text-link btn-plain" data-action="journal" data-id="${i}">Read the story <span>↗</span></button></article>`).join('')}</div>`;
}
async function homePage(n) {
 const data=await api('/api/products?featured=1');const featured=remember(data.products);
 const catImages={'Workspace':'form-desk-organiser','Lighting':'halo-desk-lamp','Drinkware':'daily-stoneware-mug','Carry':'roam-canvas-tote','Living':'still-ceramic-vase'};
 mount(`<section class="hero"><div class="hero-copy"><p class="eyebrow">THE EVERYDAY, RECONSIDERED</p><h1>Better things.<br><em>Everyday.</em></h1><p>Thoughtful essentials for the way you work, live and move. Made for the little moments that matter.</p><a href="/shop" data-link class="btn btn-dark">Discover the collection ${icon('arrow')}</a><span class="hero-note">FEWER THINGS. MORE MEANING.</span></div><div class="hero-image"><img src="/static/images/workspace-hero.png" alt="A sunlit oak workspace with a sculptural green lamp, linen notebook and ceramic mug" fetchpriority="high" width="1536" height="1024"><a href="/shop?category=Workspace" data-link class="hero-caption"><div><small>IN GOOD COMPANY</small><strong>Meet your new desk essentials</strong></div><span>↗</span></a></div></section><div class="value-strip"><div>${icon('truck')} Delivery across Pakistan</div><div>${icon('return')} 14-day returns</div><div>${icon('leaf')} Thoughtfully selected</div><div>${icon('shield')} Pay on delivery</div></div>
 <div class="container"><section class="section"><div class="section-top"><div><p class="eyebrow">GOOD COMPANY FOR YOUR EVERYDAY</p><h2>The daily favourites.</h2></div><a href="/shop" data-link class="text-link">Shop the collection <span>↗</span></a></div>${featured.length?productGrid(featured):empty('A new edit is on its way.','The collection is being refreshed. Check back shortly.',{url:'/shop',symbol:'box'})}</section>
 <section class="section"><div class="section-top"><div><p class="eyebrow">FIND YOUR EVERYDAY</p><h2>A place for everything.</h2></div></div><div class="category-grid">${state.config.categories.map(c=>`<a class="category-card" href="/shop?category=${encodeURIComponent(c)}" data-link><img src="/static/images/${catImages[c]}.svg" alt="${e(c)} essentials" loading="lazy"><div><span>${e(c)}</span><span>↗</span></div></a>`).join('')}</div></section></div>
 <section class="story-band"><div class="story-photo" role="img" aria-label="Warm natural materials in a sunlit home"></div><div class="story-content"><p class="eyebrow">A NORTHSTAR WAY OF THINKING</p><h2>Life happens in<br>the little things.</h2><p>A good cup. A clearer desk. A bag that goes everywhere. We believe the things you reach for every day should be a pleasure to use and a joy to keep.</p><a href="/about" data-link class="text-link">A little about us <span>↗</span></a></div></section>
 <div class="container"><section class="section"><div class="section-top"><div><p class="eyebrow">NOTES ON LIVING WELL</p><h2>From the journal.</h2></div><a href="/journal" data-link class="text-link">All stories <span>↗</span></a></div>${journalCards()}</section><div class="perks"><div>${icon('leaf')}<h3>Considered, always.</h3><p>Useful objects. Honest materials. Every piece earns its place in the collection.</p></div><div>${icon('box')}<h3>A little less fuss.</h3><p>Easy ordering, clear delivery fees and cash on delivery. Just the way it should be.</p></div><div>${icon('help')}<h3>Here when you need us.</h3><p>Questions about your order or your next favourite? Our help centre is a good place to start.</p></div></div></div>`,n);
}
async function shopPage(n) {
 const params=new URLSearchParams(location.search);
 const query=params.toString();
 const data=await api('/api/products'+(query?'?'+query:''));const products=remember(data.products);
 const category=params.get('category')||'';const q=params.get('q')||'';const isNew=params.get('new')==='1';
 const title=q?`Results for “${q}”`:category|| (isNew?'The latest arrivals.':'Good things, thoughtfully chosen.');
 mount(`<div class="container">${crumb('The collection')}${heading(title,'Considered essentials for your workspace, your home and everywhere in between.',isNew?'FRESH PERSPECTIVES':'THE COLLECTION')}<div class="shop-layout"><aside class="shop-sidebar" aria-label="Product filters"><form class="filter-search" id="collection-search" role="search"><label class="sr-only" for="collection-query">Search products</label><input id="collection-query" name="q" type="search" maxlength="150" value="${e(q)}" placeholder="Search the collection"><button aria-label="Search">${icon('search')}</button></form><div class="filter-section"><h3>Browse by category</h3><a href="/shop" data-link class="category-filter ${!category&&!isNew?'active':''}">All essentials</a>${state.config.categories.map(c=>`<a class="category-filter ${category===c?'active':''}" href="/shop?category=${encodeURIComponent(c)}" data-link>${e(c)}</a>`).join('')}<a href="/shop?new=1" data-link class="category-filter ${isNew?'active':''}">New arrivals</a></div><form class="filter-section" id="price-filter"><h3>Price range · PKR</h3><div class="price-fields"><label>From<input type="number" name="min_price" min="0" max="10000000" placeholder="0" value="${e(params.get('min_price')||'')}"></label><label>To<input type="number" name="max_price" min="0" max="10000000" placeholder="Any" value="${e(params.get('max_price')||'')}"></label></div><button class="btn-plain" style="margin-top:14px" type="submit">Apply range</button></form><div class="filter-section"><h3>Availability</h3><label class="check-line"><input type="checkbox" id="stock-filter" ${params.get('in_stock')==='1'?'checked':''}> In stock only</label></div></aside><section aria-label="Products"><div class="shop-toolbar"><span>${data.total} ${data.total===1?'essential':'essentials'}${category?` in ${e(category)}`:''}</span><label>Sort by <select class="sort-select" id="sort-products" aria-label="Sort products">${[['featured','Recommended'],['newest','Newest first'],['price_asc','Price: low to high'],['price_desc','Price: high to low'],['name','Name: A to Z']].map(([v,l])=>`<option value="${v}" ${params.get('sort')===v?'selected':''}>${l}</option>`).join('')}</select></label></div>${params.size?`<div class="active-filters">${q?`<span class="filter-chip">“${e(q)}”</span>`:''}${category?`<span class="filter-chip">${e(category)}</span>`:''}${isNew?'<span class="filter-chip">New arrivals</span>':''}${params.has('max_price')||params.has('min_price')?'<span class="filter-chip">Price range applied</span>':''}<a class="filter-chip" href="/shop" data-link>Clear filters ✕</a></div>`:''}${products.length?productGrid(products):empty('Nothing here, just yet.','Try a different search or clear your filters to explore the whole collection.',{symbol:'search',label:'Clear filters'})}</section></div></div>`,n);
}
async function productPage(n,slug) {
 const data=await api(`/api/products/${encodeURIComponent(slug)}`);const p=data.product;remember([p,...data.related]);
 const saved=state.wishlist.includes(p.id);
 document.title=`${p.name} — NorthStar`;
 mount(`<div class="container">${crumb(p.name,'Shop')}<div class="product-detail"><div class="product-main-img"><img src="${e(p.image)}" alt="${e(p.name)}" width="600" height="600">${p.badge?`<span class="product-badge">${e(p.badge)}</span>`:''}</div><section class="product-info"><p class="eyebrow">NORTHSTAR / ${e(p.category)}</p><h1>${e(p.name)}</h1><div class="detail-price">${money(p.price)}${p.compare_price?`<del>${money(p.compare_price)}</del>`:''}</div><p class="product-description">${e(p.description)}</p><div class="swatch-line"><span class="swatch" style="background:${e(p.color)}"></span> Signature finish</div><p class="stock-line ${!p.stock?'out':''}">${p.stock?(p.stock<5?`Only ${p.stock} left — make it yours.`:'In stock · Ready for your everyday'):'Currently out of stock · Check back soon'}</p><div class="buy-line">${quantityControl(1,Math.min(20,p.stock),'detail-quantity')}<button class="btn btn-dark" data-action="add" data-id="${p.id}" data-detail="true" ${!p.stock?'disabled':''}>${p.stock?'Add to bag':'Out of stock'} ${icon('bag')}</button><button class="icon-btn ${saved?'is-saved':''}" data-action="save" data-id="${p.id}" aria-label="${saved?'Remove from':'Save to'} wishlist" aria-pressed="${saved}">${icon('heart')}</button></div><div class="detail-perks"><span>${icon('truck')} Free delivery over Rs. 8,000</span><span>${icon('return')} 14-day returns</span></div><details open><summary>The finer details</summary><table class="spec-table">${Object.entries(p.specs).map(([k,v])=>`<tr><th scope="row">${e(k)}</th><td>${e(v)}</td></tr>`).join('')}</table></details><details><summary>Delivery & returns</summary><p>Standard delivery is Rs. 250, or complimentary when your total after discounts reaches Rs. 8,000. Expected delivery is 3–5 business days across Pakistan. Changed your mind? Contact us within 14 days of delivery. <a class="btn-plain" href="/shipping" data-link>Read the details.</a></p></details><details><summary>A little help?</summary><p>Have a question about this piece? <a href="/support" data-link class="btn-plain">Get in touch.</a> We’re happy to help you choose.</p></details></section></div>${data.related.length?`<section class="section"><div class="section-top"><h2>In good company.</h2><a class="text-link" href="/shop?category=${encodeURIComponent(p.category)}" data-link>More ${e(p.category.toLowerCase())} <span>↗</span></a></div>${productGrid(data.related)}</section>`:''}</div>`,n);
}
function quantityControl(value,max=20,id='',pid='') {
 return `<div class="quantity"><button type="button" data-action="quantity" data-step="-1" ${pid?`data-cart-id="${pid}"`:''} aria-label="Decrease quantity" ${value<=1?'disabled':''}>−</button><input ${id?`id="${id}"`:''} ${pid?`data-cart-id="${pid}"`:''} type="number" min="1" max="${Math.max(1,max)}" value="${value}" aria-label="Quantity" readonly><button type="button" data-action="quantity" data-step="1" ${pid?`data-cart-id="${pid}"`:''} aria-label="Increase quantity" ${value>=max?'disabled':''}>+</button></div>`;
}
async function authPage(n,register=false) {
 if (state.user) return navigate('/account',{replace:true});
 mount(`<div class="container"><div class="auth-wrap"><div class="auth-photo"><div><p class="eyebrow">A PLACE FOR THE EVERYDAY</p><h2>Good to<br>have you here.</h2><p>Save your favourites, keep track of your orders and make yourself at home.</p></div></div><section class="auth-form-wrap"><p class="eyebrow">${register?'MAKE YOURSELF AT HOME':'WELCOME BACK'}</p><h1>${register?'Your everyday starts here.':'Hello again.'}</h1><p>${register?'A few details, and you’re part of the NorthStar edit.':'Sign in for a little more NorthStar.'}</p><form id="${register?'register-form':'login-form'}">${errorBox()}${register?field('name','Full name','',{max:80,min:2,autocomplete:'name'}):''}${field('email','Email address','',{type:'email',max:254,autocomplete:'email',placeholder:'you@example.com'})}${field('password','Password','',{type:'password',min:register?8:1,max:128,autocomplete:register?'new-password':'current-password',hint:register?'At least 8 characters, including a letter and a number.':''})}${register?`<label class="check-line" style="margin:20px 0"><input type="checkbox" name="terms" required><span>I agree to the <a href="/terms" data-link class="btn-plain">terms</a> and <a href="/privacy" data-link class="btn-plain">privacy policy</a>.</span></label>`:''}<button class="btn btn-dark btn-block" type="submit">${register?'Create account':'Sign in'} ${icon('arrow')}</button></form><p class="auth-switch">${register?'Already at home here?':'New around here?'} <a href="/${register?'login':'register'}${location.search}" data-link>${register?'Sign in':'Create an account'}</a></p>${!register?`<div class="demo-note"><strong>Explore the local shop</strong>Customer: alex@northstar.local · NorthStar123!<br>Admin: admin@northstar.local · NorthStarAdmin123!<br><button data-action="demo-login" data-role="customer">Fill customer details ↗</button><button data-action="demo-login" data-role="admin">Fill admin details ↗</button></div>`:''}</section></div></div>`,n);
}
async function wishlistPage(n) {
 if (!state.user) return signInGate(n,'Good things are worth keeping.','Sign in to save your favourites and find them here whenever you return.','heart');
 const data=await api('/api/wishlist');remember(data.products);
 mount(`<div class="container">${crumb('Saved for later')}${heading('Your little collection.','The pieces you have your eye on, all in one place.','SAVED FOR LATER')}${data.products.length?productGrid(data.products):empty('Room for a few favourites.','Tap the heart on something you love and we’ll keep it here for you.',{symbol:'heart'})}</div>`,n);
}
function signInGate(n,title,message,symbol='user') {
 return mount(`<div class="container section">${empty(title,message,{symbol,url:'/login?next='+encodeURIComponent(location.pathname+location.search),label:'Sign in to continue'})}</div>`,n);
}
function summaryLines(cart) {
 return `<div class="summary-line"><span>Subtotal</span><span>${money(cart.subtotal)}</span></div>${cart.discount?`<div class="summary-line discount"><span>Promo discount</span><span>− ${money(cart.discount)}</span></div>`:''}<div class="summary-line"><span>Delivery</span><span>${cart.shipping?money(cart.shipping):'Complimentary'}</span></div><div class="summary-line total"><span>Total <small class="fineprint">PKR</small></span><strong>${money(cart.total)}</strong></div>`;
}
function promoForm(cart) {
 return `${cart.coupon?`<div class="coupon-tag"><span>${e(cart.coupon)}${cart.coupon_applied?' · Applied':' · Minimum not met'}</span><button data-action="remove-coupon" aria-label="Remove promo code">×</button></div>${cart.coupon_message?`<p class="fineprint">${e(cart.coupon_message)}</p>`:''}`:`<form class="promo-form" id="promo-form"><label for="promo-code">Have a promo code?</label><div class="promo-row"><input id="promo-code" name="code" placeholder="Enter code" required maxlength="30"><button type="submit">Apply</button></div>${errorBox()}</form>`}`;
}
async function cartPage(n) {
 const cart=await api('/api/cart');state.cartCount=cart.count;updateHeader();remember(cart.items);
 mount(`<div class="container">${crumb('Shopping bag')}${heading('In your bag.',`${cart.count} ${cart.count===1?'good thing':'good things'}, ready for your everyday.`,'GOOD CHOICES')}${!cart.items.length?empty('A little room for something good.','Your bag is empty. Let’s find something you’ll love.'): `<div class="cart-layout"><section aria-label="Shopping bag items"><div class="shipping-progress">${cart.subtotal-cart.discount>=8000?'Your delivery is on us. A little thank you.':`You’re ${money(8000-cart.subtotal+cart.discount)} away from complimentary delivery.`}<div class="progress-track"><span style="width:${Math.min(100,(cart.subtotal-cart.discount)/80)}%"></span></div></div><div class="cart-table-head"><span>THE GOOD THINGS</span><span>PRICE</span></div>${cart.items.map(p=>`<article class="cart-item"><img src="${e(p.image)}" alt="${e(p.name)}"><div><h3><a href="/product/${e(p.slug)}" data-link>${e(p.name)}</a></h3><p>${e(p.category)} · ${money(p.price)} each</p><div class="item-controls">${quantityControl(p.quantity,Math.min(p.stock,20),'',p.id)}<button class="btn-plain" data-action="remove-cart" data-id="${p.id}" aria-label="Remove ${e(p.name)} from bag">Remove</button></div>${p.quantity>p.stock||!p.active?'<p style="color:var(--red);margin-top:10px">Availability changed. Please remove or reduce this item.</p>':''}</div><div class="item-price">${money(p.line_total)}</div></article>`).join('')}<a href="/shop" data-link class="text-link" style="margin-top:23px">Keep exploring <span>↗</span></a></section><aside class="cart-summary"><h2>The good total.</h2>${summaryLines(cart)}${promoForm(cart)}<a href="/checkout" data-link class="btn btn-dark btn-block">Continue to checkout ${icon('arrow')}</a><p class="fineprint" style="margin-top:16px;text-align:center">${icon('shield')} Cash on delivery · No payment details needed</p><hr><p class="fineprint">A little welcome: use <strong>WELCOME10</strong> for 10% off a subtotal of Rs. 3,000 or more. Up to Rs. 2,000 off.</p></aside></div>`}</div>`,n);
}
function addressFields(a={}) {
 return `${field('name','Full name',a.name||state.user?.name||'',{min:2,max:80,autocomplete:'name'})}${field('phone','Mobile number',a.phone||state.user?.phone||'',{type:'tel',min:10,max:20,placeholder:'03001234567',autocomplete:'tel',hint:'For delivery updates. Use 03XXXXXXXXX or +923XXXXXXXXX.'})}${field('line1','Street address',a.line1||'',{min:5,max:160,placeholder:'House / flat number and street',autocomplete:'address-line1'})}${field('line2','Area / landmark',a.line2||'',{required:false,max:160,autocomplete:'address-line2'})}<div class="form-row">${selectField('city','City',state.config.cities,a.city||'')}${field('postal_code','Postal code',a.postal_code||'',{min:5,max:5,pattern:'[0-9]{5}',placeholder:'75300',autocomplete:'postal-code'})}</div>`;
}
async function checkoutPage(n) {
 if (!state.user) return signInGate(n,'One step closer.','Sign in or create an account to check out and keep track of your order.','bag');
 const [cart,addresses]=await Promise.all([api('/api/cart'),api('/api/addresses')]);
 state.addresses=addresses.addresses;
 if (!cart.items.length) return mount(`<div class="container section">${empty('Your bag is waiting.','Add something good to your bag before checking out.')}</div>`,n);
 checkoutKey=(crypto.randomUUID?crypto.randomUUID():`${Date.now()}-${Math.random().toString(36).slice(2)}-northstar`);
 mount(`<div class="container">${crumb('Checkout')}${heading('Nearly yours.','','THE FINAL DETAILS')}<div class="checkout-layout"><form id="checkout-form">${errorBox()}<section class="panel"><h2>Where shall we send it?</h2>${addresses.addresses.length?`<div class="field checkout-address-choice"><label for="saved-address">Use a saved address</label><select id="saved-address"><option value="">Enter a new address</option>${addresses.addresses.map(a=>`<option value="${a.id}">${e(a.label)} · ${e(a.line1)}, ${e(a.city)}</option>`).join('')}</select></div>`:''}<div id="checkout-address-fields">${addressFields()}</div><label class="check-line"><input type="checkbox" name="save_address"> Save this address for next time</label></section><section class="panel"><h2>Payment, made simple.</h2><label class="payment-option"><input type="radio" name="payment_method" value="cod" checked required><div><strong>Cash on delivery</strong><p>Pay ${money(cart.total)} when your order arrives. No card details needed.</p></div></label></section><section class="panel"><div class="field"><label for="order-note">Anything we should know? <span class="optional">(optional)</span></label><textarea id="order-note" name="note" rows="3" maxlength="500" placeholder="Delivery instructions, a useful landmark…"></textarea></div><label class="check-line"><input type="checkbox" name="terms" required><span>I agree to the <a class="btn-plain" href="/terms" data-link>order terms</a> and <a class="btn-plain" href="/shipping" data-link>delivery policy</a>.</span></label></section><button class="btn btn-dark btn-block" type="submit">Place order · ${money(cart.total)} ${icon('arrow')}</button><p class="fineprint" style="text-align:center;margin-top:12px">Expected delivery: 3–5 business days. You can cancel before dispatch.</p></form><aside class="cart-summary"><h2>Coming your way.</h2>${cart.items.map(p=>`<div class="checkout-mini"><img src="${e(p.image)}" alt=""><div>${e(p.name)}<p>Qty ${p.quantity}</p></div><span>${money(p.line_total)}</span></div>`).join('')}<hr>${summaryLines(cart)}${cart.coupon_applied?`<p class="fineprint" style="margin-top:13px">${e(cart.coupon)} has been applied.</p>`:''}<a class="btn-plain" href="/cart" data-link style="display:inline-block;margin-top:20px">Edit your bag</a></aside></div></div>`,n);
}

function accountNav(tab) {
 return `<aside class="account-sidebar" aria-label="Account navigation">${[
  ['/orders','orders','box','My orders'],['/account?tab=wishlist','wishlist','heart','Saved items'],['/account?tab=addresses','addresses','pin','Addresses'],['/account','profile','user','Profile & security'],['/account?tab=support','support','help','Support requests'],
  ...(state.user?.role==='admin'?[['/admin','admin','settings','Admin studio']]:[])
 ].map(([url,key,symbol,label])=>`<a href="${url}" data-link class="${tab===key?'active':''}">${icon(symbol)} ${label}</a>`).join('')}<button data-action="logout">${icon('logout')} Sign out</button></aside>`;
}
async function accountPage(n,forcedTab='') {
 if (!state.user) return signInGate(n,'Make yourself at home.','Sign in to manage your orders, favourites and account details.');
 const tab=forcedTab||new URLSearchParams(location.search).get('tab')||'profile';
 let content='';
 if (tab==='orders') {
  const {orders}=await api('/api/orders');
  content=`<h2>Your good choices.</h2><p class="subtle" style="font-size:12px;margin-bottom:25px">Every order, all in one place.</p>${orders.length?orders.map(o=>`<article class="order-card"><div class="order-card-top"><div><h3>${e(o.number)}</h3><p>Placed ${date(o.created_at)} · ${o.items.reduce((sum,p)=>sum+p.quantity,0)} items</p></div>${status(o.status)}</div><div class="order-thumbs">${o.items.slice(0,5).map(p=>`<img src="${e(p.image)}" alt="${e(p.name)}">`).join('')}</div><div class="order-card-bottom"><strong>${money(o.total)}</strong><a href="/orders/${e(o.number)}" data-link class="btn btn-small">View order ${icon('arrow')}</a></div></article>`).join(''):empty('The start of something good.','Your first order will find a home here.',{symbol:'box'})}`;
 } else if (tab==='addresses') {
  const {addresses}=await api('/api/addresses');state.addresses=addresses;
  content=`<h2>A place to call home.</h2><p class="subtle" style="font-size:12px;margin-bottom:25px">Save an address for an easier checkout next time.</p><div class="address-grid">${addresses.map(a=>`<article class="address-card"><h3>${e(a.label)}</h3><p>${e(a.name)}<br>${e(a.line1)}${a.line2?`<br>${e(a.line2)}`:''}<br>${e(a.city)}, ${e(a.postal_code)}<br>${e(a.phone)}</p><div class="button-row"><button class="btn-plain" data-action="edit-address" data-id="${a.id}">Edit address</button><button class="btn-plain" data-action="delete-address" data-id="${a.id}">Remove</button></div></article>`).join('')}<button class="address-add" data-action="new-address"><span>+</span>Add a new address</button></div>`;
 } else if (tab==='wishlist') {
  const {products}=await api('/api/wishlist');remember(products);
  content=`<h2>Your little collection.</h2>${products.length?productGrid(products):empty('Room for a few favourites.','Tap the heart on something you love and we’ll keep it here for you.',{symbol:'heart'})}`;
 } else if (tab==='support') {
  const {tickets}=await api('/api/support');
  content=`<div class="section-top"><h2>We’re here to help.</h2><a class="text-link" href="/support" data-link>New message <span>↗</span></a></div>${tickets.length?tickets.map(ticketCard).join(''):empty('All quiet here.','Have a question? Send us a message and follow the conversation here.',{symbol:'help',url:'/support',label:'Get in touch'})}`;
 } else {
  content=`<h2>A little about you.</h2><form id="profile-form" class="panel">${errorBox()}${field('name','Full name',state.user.name,{min:2,max:80,autocomplete:'name'})}${field('email','Email address',state.user.email,{type:'email',readonly:true})}${field('phone','Mobile number',state.user.phone,{type:'tel',required:false,max:20,autocomplete:'tel',placeholder:'03001234567'})}<p class="fineprint">Your email is your account identifier. Contact support if you need help changing it.</p><button class="btn btn-dark" type="submit">Save changes ${icon('check')}</button></form><form id="password-form" class="panel"><h3>A little more peace of mind.</h3>${errorBox()}${field('current_password','Current password','',{type:'password',autocomplete:'current-password',max:128})}<div class="form-row">${field('new_password','New password','',{type:'password',min:8,max:128,autocomplete:'new-password'})}${field('confirm_password','Confirm new password','',{type:'password',min:8,max:128,autocomplete:'new-password'})}</div><p class="fineprint">Use at least 8 characters, including a letter and a number.</p><button class="btn btn-dark" type="submit">Update password ${icon('arrow')}</button></form>`;
 }
 mount(`<div class="container">${crumb(tab==='orders'?'My orders':'Your account')}${heading(`Hello, ${state.user.name.split(' ')[0]}.`,'Good to have you back. Make yourself at home.','YOUR NORTHSTAR')}<div class="account-layout">${accountNav(tab)}<section class="account-main">${content}</section></div></div>`,n);
}
function ticketCard(t,admin=false) {
 return `<article class="ticket-card"><div class="order-card-top"><p class="fineprint">${e(t.reference)} · ${date(t.created_at)}</p>${status(t.status)}</div><h3>${e(t.subject)}</h3>${admin?`<p class="fineprint">${e(t.name)} · ${e(t.email)}</p>`:''}<p class="message">${e(t.message)}</p>${t.response?`<div class="ticket-response"><strong>NorthStar replied</strong>${e(t.response)}</div>`:'<p class="fineprint">Your message is in our queue.</p>'}${admin?`<button class="btn btn-small" style="margin-top:18px" data-action="reply-ticket" data-id="${t.id}">${t.response?'Edit response':'Write a response'} ↗</button>`:''}</article>`;
}
function orderBody(o,admin=false) {
 const a=o.address;
 return `<div class="order-grid"><section class="panel"><h3>The journey so far.</h3><ol class="timeline">${o.events.map(x=>`<li><h4>${e(x.status)}</h4><p>${e(x.note)}</p><time datetime="${e(x.created_at)}">${date(x.created_at)}</time></li>`).join('')}</ol></section><section class="panel order-info"><h3>Heading your way.</h3><p>${e(a.name)}<br>${e(a.line1)}${a.line2?`<br>${e(a.line2)}`:''}<br>${e(a.city)}, ${e(a.postal_code)}<br>${e(a.phone)}</p><hr><p><strong>Payment:</strong> Cash on delivery<br>${o.status==='Cancelled'?'No payment due.':o.status==='Delivered'?'Order marked delivered.':'Payment is due when your order arrives.'}</p>${o.note?`<p style="margin-top:12px"><strong>Your note:</strong> ${e(o.note)}</p>`:''}</section></div><section class="panel"><h3>The good things.</h3>${o.items.map(p=>`<div class="checkout-mini"><img src="${e(p.image)}" alt="${e(p.name)}"><div>${e(p.name)}<p>Qty ${p.quantity} · ${money(p.price)} each</p></div><span>${money(p.price*p.quantity)}</span></div>`).join('')}<hr>${summaryLines(o)}${o.coupon?`<p class="fineprint">${e(o.coupon)} was applied.</p>`:''}</section>${!admin?`<div class="button-row"><a class="btn btn-dark" href="/shop" data-link>Keep exploring ${icon('arrow')}</a><a class="btn" href="/support" data-link>Need a hand?</a></div>`:''}`;
}
async function orderPage(n,number) {
 if (!state.user) return signInGate(n,'Your order, all in one place.','Sign in to see your order and delivery updates.','box');
 const {order:o}=await api(`/api/orders/${encodeURIComponent(number)}`);const confirmed=new URLSearchParams(location.search).has('confirmed');
 mount(`<div class="container">${crumb(o.number)}<div class="order-details-wrap">${confirmed?`<div class="order-confirm"><div class="confirm-tick">✓</div><p class="eyebrow">A VERY GOOD CHOICE</p><h1>Good things are on their way.</h1><p>Your order is confirmed. We’ll keep its progress here, so you always know where things stand.</p><p><strong>${e(o.number)}</strong></p></div>`:''}<div class="order-header"><div>${!confirmed?`<p class="eyebrow">YOUR NORTHSTAR ORDER</p><h1>${e(o.number)}</h1>`:''}<p>Placed ${date(o.created_at)} · ${status(o.status)}</p></div><div class="button-row">${['Confirmed','Processing'].includes(o.status)?`<button class="btn btn-small btn-danger" data-action="cancel-order" data-number="${e(o.number)}">Cancel order</button>`:''}<a class="btn btn-small" href="/orders" data-link>All orders</a></div></div>${orderBody(o)}</div></div>`,n);
}
const faqs=[
 ['Where do you deliver?','We deliver across Pakistan. Standard delivery takes an estimated 3–5 business days after dispatch; remote areas may take longer. Choose “Other” at checkout if your city is not listed and put the district in the address line.'],
 ['How much does delivery cost?','Standard delivery is Rs. 250. Delivery is complimentary when your merchandise total, after any promo discount, reaches Rs. 8,000. The final amount is always shown before you place your order.'],
 ['How do I pay?','Cash on delivery keeps it simple. Pay the total shown on your order when it arrives. The local NorthStar shop does not collect card details or process online payments.'],
 ['Can I change or cancel an order?','You can cancel a Confirmed or Processing order from My orders before it is marked Shipped. For changes to an address or the contents of an existing order, cancel and place a new order, or send a support request.'],
 ['What is the returns policy?','Contact us within 14 days of delivery for a return request. Items should be unused, with original packaging. Tell us the order number and the reason in your message. Damaged or incorrect items should be reported as soon as possible.'],
 ['Where can I find a reply to my message?','When you send a message while signed in, it appears in Account → Support requests. NorthStar’s admin can reply there. Guest messages are saved for the shop team, but this local version does not send email. Sign in before sending if you want to follow the reply in your account.'],
 ['Is there a welcome offer?','Use WELCOME10 for 10% off a merchandise subtotal of Rs. 3,000 or more, up to Rs. 2,000 off. WORKSPACE15 gives 15% off a subtotal of Rs. 10,000 or more, up to Rs. 3,000 off. One code per order. Delivery eligibility is calculated after the discount.']
];
function supportPage(n) {
 mount(`<div class="container">${crumb('Here to help')}<div class="support-intro">${heading('A little help, a human touch.','A question, a suggestion or something not quite right? We’re here to help make your everyday a little easier.','HERE TO HELP')}</div><div class="support-layout"><section><h2>Let’s talk.</h2><form id="support-form">${errorBox()}<div class="form-row">${field('name','Your name',state.user?.name||'',{min:2,max:80,autocomplete:'name'})}${field('email','Email address',state.user?.email||'',{type:'email',max:254,autocomplete:'email'})}</div>${field('subject','What can we help with?','',{min:3,max:120,placeholder:'An order question, a product detail…'})}<div class="field"><label for="support-message">Your message</label><textarea id="support-message" name="message" required minlength="20" maxlength="3000" rows="6" placeholder="Tell us a little more. If it’s about an order, include your order number."></textarea><p class="fineprint">Please use at least 20 characters so we have enough detail to help.</p></div><button class="btn btn-dark" type="submit">Send your message ${icon('arrow')}</button><p class="fineprint" style="margin-top:16px">${state.user?'Follow the reply in Account → Support requests.':'Sign in before sending to track replies in your account. Guest messages are saved; email delivery is not connected.'}</p></form><div class="support-meta"><div><strong>Good to know</strong>Keep your order number handy.</div><div><strong>A little patience</strong>Replies appear in your account.</div></div></section><section><h2>A few good answers.</h2>${faqs.map(([q,a])=>`<details><summary>${e(q)}</summary><p>${e(a)}</p></details>`).join('')}</section></div></div>`,n);
}
function aboutPage(n) {
 mount(`<div class="container">${crumb('Our story')}<section class="editorial-hero"><div><p class="eyebrow">THE NORTHSTAR WAY</p><h1>Less noise.<br>More meaning.</h1><p>NorthStar starts with a simple idea: the things around us shape the way we feel. A thoughtfully arranged desk. A mug that fits just right. A reliable bag by the door.</p><p>We bring together useful, quietly beautiful objects for work, home and everywhere in between. Pieces that do their job well, feel good to use and make ordinary days a little better.</p><a class="text-link" href="/shop" data-link>Find your everyday <span>↗</span></a></div><img src="/static/images/workspace-hero.png" alt="Warm light falling on carefully chosen everyday objects"></section><section class="story-values"><div><span>01 / USEFUL FIRST</span><h2>Purpose in every piece.</h2><p>Something earns its place when it solves a small problem well. Our collection favours function, clarity and the kind of details you appreciate with use.</p></div><div><span>02 / QUIETLY BEAUTIFUL</span><h2>Design that feels at home.</h2><p>Natural colours, considered proportions and tactile finishes. Objects that work together without needing to match.</p></div><div><span>03 / EVERYDAY EASE</span><h2>A simpler way to shop.</h2><p>Clear prices in Pakistani rupees. Straightforward delivery. Helpful product information. And a place to ask when you need a little guidance.</p></div></section></div>`,n);
}
const stories=[
 {title:'A calmer desk. A clearer mind.',tag:'SPACES',body:`<p>A workspace doesn’t need a complete reinvention to feel better. Often, the most useful change is a small one: moving a lamp, making room for a notebook or giving loose cables a place to live.</p><h3>Start with what you actually use.</h3><p>Clear the surface and put back only what you reach for every day. The rest can find a home in a drawer or a tray. A little open space makes it easier to settle into the task in front of you.</p><h3>Let the light do its work.</h3><p>Place your desk near natural light if you can. A warm desk lamp adds a softer layer for early starts and late finishes. Keep the light beside your working hand to reduce shadows across the page.</p><h3>Make one place for the small things.</h3><p>Pens, clips and charging cables are useful. Scattered everywhere, they become noise. An organiser or a small pouch creates a reliable place to put them down—and find them again.</p><p>The goal is a desk that supports your day. A place you’re happy to sit down, rather than a photograph you’re afraid to disturb.</p>`},
 {title:'The art of a slower morning.',tag:'RITUALS',body:`<p>Some mornings move quickly. That doesn’t mean every part of them has to. One small ritual can give the day a softer beginning.</p><h3>A familiar cup.</h3><p>Choose a mug you enjoy holding. Make something warm. Give it a moment before you pick up your phone. That pause might last two minutes or ten; the point is to notice it.</p><h3>A page without a plan.</h3><p>Keep a notebook nearby. Write a few things you want to do, a thought you want to keep or something you’re looking forward to. The page doesn’t need to be neat. It only needs to be yours.</p><h3>Take a little care forward.</h3><p>Fill a bottle for the day. Put the things you need in your bag. Open a window. These ordinary actions can become small ways of looking after your future self.</p><p>A slower morning is less about extra time and more about a little attention to the time you already have.</p>`},
 {title:'Carry less. Make room for more.',tag:'ON THE MOVE',body:`<p>There is a particular kind of ease in leaving the house with what you need, and knowing where to find it.</p><h3>Give the essentials a home.</h3><p>A small pouch keeps cables together. An inside pocket gives keys a reliable place to land. Choose a bag with enough structure for your day, without so many compartments that things disappear.</p><h3>Pack for the day you’re having.</h3><p>A bottle, a notebook, a light layer. Think about where you’re going and what you’ll actually use. Empty your bag at the end of the week; receipts and “just in case” objects have a habit of settling in.</p><h3>Choose things that travel well.</h3><p>Comfortable straps, washable materials and a sturdy closure matter more than they first appear. Look at the everyday details as closely as the overall shape.</p><p>A good carryall creates room for the things that happen along the way: a book, a market find or an unplanned change of direction.</p>`}
];
const legal={
 shipping:{title:'Good things, on their way.',tag:'DELIVERY & RETURNS',body:`<h2>Delivery across Pakistan.</h2><p>Standard delivery is Rs. 250. Orders with a merchandise total of Rs. 8,000 or more after discounts receive complimentary delivery. The exact fee is displayed in your bag and again before you place an order.</p><p>The shop’s delivery estimate is 3–5 business days after dispatch. Remote areas and public holidays can affect this estimate. For this local demonstration, dispatch and delivery statuses are updated by the shop administrator; no courier service is connected.</p><h2>Cash on delivery.</h2><p>Payment is due when your order arrives. NorthStar does not ask for card details. No real payment or courier booking is triggered by this local website.</p><h2>A little change of plan.</h2><p>You can cancel an order in My orders while it is Confirmed or Processing. Cancellation releases the reserved stock. Once the order is Shipped, contact support for help.</p><h2>14-day returns.</h2><p>Send a support request within 14 days of delivery, with your order number and reason. Items should be unused and in their original packaging. Report damaged or incorrect items as soon as possible. Return requests are handled through support; automated refunds are not part of this shop.</p><p><a href="/support" data-link>We’re here if you need a hand.</a></p>`},
 privacy:{title:'Your details, treated with care.',tag:'PRIVACY POLICY',body:`<p>Last updated: 28 October 2026.</p><h2>What this shop stores.</h2><p>NorthStar stores the account details you provide, saved addresses, favourites, cart contents, orders, newsletter subscriptions and support messages in its local SQLite database. Passwords are stored as salted hashes. Session cookies keep you signed in and connect your shopping bag to your browser.</p><h2>How information is used.</h2><p>Your details support the features you choose to use: signing in, checking out, following orders and receiving support in your account. Administrative users can view orders and support requests to manage the shop.</p><h2>No external tracking.</h2><p>This application has no third-party analytics, advertising trackers, remote fonts or external payment service. Product artwork and the editorial image are bundled locally. Newsletter subscriptions are saved, but marketing email is not sent.</p><h2>Your choices.</h2><p>You can edit your profile, change your password, remove saved addresses and delete saved items from your account. Signing out ends the current session. For account deletion or other requests, contact the shop administrator through the support form. The administrator may manage the local database; automated account deletion is not provided.</p><h2>Local demonstration.</h2><p>This is a fictional shop built for local use. The machine running it stores its data in the instance folder. Use sample personal details for demonstrations. No information is sold or shared by this application.</p>`},
 terms:{title:'A few things to know.',tag:'TERMS OF SERVICE',body:`<p>Last updated: 28 October 2026.</p><h2>About NorthStar.</h2><p>NorthStar is a fictional retail website for local demonstration and coursework. It offers working accounts, catalogue browsing, carts, orders and support. Orders are application records; no actual goods are sold or dispatched by this software.</p><h2>Prices and availability.</h2><p>Prices are shown in Pakistani rupees. The server calculates the final total and checks current stock when an order is placed. Placing an order reserves stock. An item in a bag is not reserved until checkout is completed.</p><h2>Offers.</h2><p>WELCOME10 takes 10% off a merchandise subtotal of at least Rs. 3,000, capped at Rs. 2,000. WORKSPACE15 takes 15% off a merchandise subtotal of at least Rs. 10,000, capped at Rs. 3,000. One code may be applied to an order. Discounts are rounded down to whole rupees. Delivery fees are calculated after discounts.</p><h2>Accounts and orders.</h2><p>Keep your password private. Use accurate sample delivery details for your order. You may cancel before dispatch through your account. Admin users manage order progress, catalogue availability and support replies.</p><h2>Need help?</h2><p>Read our <a href="/shipping" data-link>delivery and returns information</a> or <a href="/support" data-link>send us a message</a>. This application does not send transactional emails or process online payments.</p>`}
};
function articlePage(n,page) {
 const a=legal[page];
 mount(`<div class="container">${crumb(a.tag)}<article class="prose"><p class="eyebrow">${a.tag}</p><h1>${a.title}</h1>${a.body}</article></div>`,n);
}
function adminNav(tab) {
 return `<nav class="admin-nav" aria-label="Admin navigation">${[['/admin','overview','Overview'],['/admin/products','products','Catalogue'],['/admin/orders','orders','Orders'],['/admin/support','support','Support inbox']].map(([url,key,label])=>`<a href="${url}" data-link class="${tab===key?'active':''}">${label}</a>`).join('')}<a href="/account" data-link>My account ↗</a></nav>`;
}
function adminProductRows(products) {
 return products.map(p=>`<tr><td><div class="product-cell"><img src="${e(p.image)}" alt=""><div>${e(p.name)}<small>${e(p.slug)}</small></div></div></td><td>${e(p.category)}</td><td>${money(p.price)}</td><td>${p.stock}${p.stock<5?' · Low':''}</td><td>${status(p.active?'Active':'Archived')}</td><td><div class="button-row"><button class="btn-plain" data-action="edit-product" data-id="${p.id}">Edit</button>${p.active?`<button class="btn-plain" data-action="archive-product" data-id="${p.id}">Archive</button>`:`<button class="btn-plain" data-action="restore-product" data-id="${p.id}">Restore</button>`}</div></td></tr>`).join('');
}
async function adminPage(n,tab='overview') {
 if (!state.user) return signInGate(n,'Welcome to the studio.','Sign in with the administrator account to manage NorthStar.','settings');
 if (state.user.role!=='admin') return mount(`<div class="container section">${empty('This space is for the shop team.','Your account does not have administrator access.',{symbol:'shield',url:'/account',label:'Back to your account'})}</div>`,n);
 let html='';
 if (tab==='overview') {
  const [{stats:s},{orders},{products}]=await Promise.all([api('/api/admin/overview'),api('/api/admin/orders'),api('/api/admin/products')]);
  state.adminOrders=orders;state.adminProducts=products;
  html=`<div class="admin-stats">${[['Delivered revenue',money(s.revenue)],['Orders received',s.orders],['Customer accounts',s.customers],['Open support requests',s.open_tickets]].map(([l,v])=>`<div class="stat-card"><p>${l}</p><strong>${e(v)}</strong></div>`).join('')}</div><div class="order-grid"><section class="panel"><h3>A little attention needed.</h3><p>${s.low_stock} active ${s.low_stock===1?'product is':'products are'} running low on stock.</p>${products.filter(p=>p.active&&p.stock<5).map(p=>`<div class="checkout-mini"><img src="${e(p.image)}" alt=""><div>${e(p.name)}<p>${p.stock} remaining</p></div><button class="btn-plain" data-action="edit-product" data-id="${p.id}">Update</button></div>`).join('')}<a class="text-link" href="/admin/products" data-link>Manage catalogue <span>↗</span></a></section><section class="panel"><h3>The latest good choices.</h3>${orders.length?orders.slice(0,5).map(o=>`<div style="padding:12px 0;border-bottom:1px solid var(--line)"><button class="btn-plain" data-action="admin-order-detail" data-number="${e(o.number)}">${e(o.number)}</button><p class="fineprint" style="margin:7px 0 0">${e(o.customer_name)} · ${money(o.total)} · ${e(o.status)}</p></div>`).join(''):'<p>Your first order will appear here.</p>'}<a class="text-link" href="/admin/orders" data-link>All orders <span>↗</span></a></section></div><div class="info-box"><strong>Your shop, connected.</strong> Catalogue changes appear in the storefront immediately. Orders reserve stock at checkout, and cancellations restore it. Customer support replies appear in the customer’s account. Newsletter addresses are saved locally; email and courier integrations are not connected.</div>`;
 } else if (tab==='products') {
  const {products}=await api('/api/admin/products');state.adminProducts=products;
  html=`<div class="admin-toolbar"><h2>The collection.</h2><input id="admin-product-search" type="search" placeholder="Find a product…" aria-label="Filter admin products"><button class="btn btn-dark btn-small" data-action="new-product">Add product +</button></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Product</th><th>Category</th><th>Price</th><th>Stock</th><th>Visibility</th><th>Actions</th></tr></thead><tbody id="admin-product-rows">${adminProductRows(products)}</tbody></table></div><p class="fineprint" style="margin-top:18px">Archiving removes a product from the shop while preserving order history. Restore it at any time.</p>`;
 } else if (tab==='orders') {
  const {orders}=await api('/api/admin/orders');state.adminOrders=orders;
  const next={'Confirmed':['Processing','Cancelled'],'Processing':['Shipped','Cancelled'],'Shipped':['Delivered'],'Delivered':[],'Cancelled':[]};
  html=`<div class="admin-toolbar"><h2>From bag to doorstep.</h2><span class="fineprint">${orders.length} orders</span></div>${orders.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Order</th><th>Customer</th><th>Date</th><th>Total</th><th>Status</th><th>Next step</th></tr></thead><tbody>${orders.map(o=>`<tr><td><button class="btn-plain" data-action="admin-order-detail" data-number="${e(o.number)}">${e(o.number)}</button></td><td>${e(o.customer_name)}<br><span class="fineprint">${e(o.customer_email)}</span></td><td>${date(o.created_at)}</td><td>${money(o.total)}</td><td>${status(o.status)}</td><td>${next[o.status].length?`<div class="button-row"><select aria-label="Next status for ${e(o.number)}" id="status-${e(o.number)}">${next[o.status].map(s=>`<option>${s}</option>`).join('')}</select><button class="btn-plain" data-action="update-order" data-number="${e(o.number)}">Update</button></div>`:'<span class="fineprint">Complete</span>'}</td></tr>`).join('')}</tbody></table></div>`:empty('Ready for the first good choice.','Customer orders will appear here once they check out.',{symbol:'box',url:'/shop',label:'Visit the shop'})}`;
 } else {
  const {tickets}=await api('/api/admin/tickets');state.tickets=tickets;
  html=`<div class="admin-toolbar"><h2>A little human help.</h2><span class="fineprint">${tickets.filter(t=>t.status==='Open').length} open messages</span></div>${tickets.length?tickets.map(t=>ticketCard(t,true)).join(''):empty('All quiet in the inbox.','New support messages will find their way here.',{symbol:'mail',url:'',label:''})}`;
 }
 mount(`<div class="container">${crumb('Admin studio')}${heading('Behind the everyday.','A little care keeps everything running smoothly.','NORTHSTAR STUDIO')}${adminNav(tab)}${html}</div>`,n);
}
async function renderRoute(scroll=true) {
 const n=++renderNumber;
 document.title='NorthStar — Better things. Everyday.';updateHeader();
 $('#main').setAttribute('aria-busy','true');
 $('#main').innerHTML='<div class="page-loader"><span class="spinner"></span><p>Getting things ready…</p></div>';
 if (scroll) window.scrollTo(0,0);
 const path=location.pathname.replace(/\/$/,'')||'/';
 try {
  if (!state.sessionReady) await refreshSession();
  if (n!==renderNumber) return;
  if (path==='/') await homePage(n);
  else if (path==='/shop') await shopPage(n);
  else if (path.startsWith('/product/')) await productPage(n,path.split('/')[2]);
  else if (path==='/login'||path==='/register') await authPage(n,path==='/register');
  else if (path==='/wishlist') await wishlistPage(n);
  else if (path==='/cart') await cartPage(n);
  else if (path==='/checkout') await checkoutPage(n);
  else if (path==='/orders') await accountPage(n,'orders');
  else if (path.startsWith('/orders/')) await orderPage(n,path.split('/')[2]);
  else if (path==='/account') await accountPage(n);
  else if (path==='/support') supportPage(n);
  else if (path==='/about') aboutPage(n);
  else if (path==='/journal') mount(`<div class="container">${crumb('The journal')}${heading('Notes on living well.','Little ideas for better days. A collection of spaces, rituals and everyday inspiration.','THE JOURNAL')}<section style="padding:15px 0 50px">${journalCards()}</section></div>`,n);
  else if (legal[path.slice(1)]) articlePage(n,path.slice(1));
  else if (['/admin','/admin/products','/admin/orders','/admin/support'].includes(path)) await adminPage(n,path.split('/')[2]||'overview');
  else mount(`<div class="container section">${empty('A little off the beaten path.','We couldn’t find this page. Let’s get you back to something good.',{symbol:'pin',url:'/',label:'Back to NorthStar'})}</div>`,n);
 } catch (err) {
  if (n!==renderNumber) return;
  retryAction=()=>renderRoute(false);
  const missing=err.status===404;
  mount(`<div class="container section">${empty(missing?'We couldn’t find that.':'A little pause in the everyday.',err.message,{symbol:missing?'search':'return',url:missing?'/shop':'',action:missing?'':'retry',label:missing?'Back to the collection':'Try again'})}</div>`,n);
 }
}

function modal(html) {
 $('#modal-content').innerHTML=html;
 if (!$('#modal').open) $('#modal').showModal();
}
function confirmAction(title,message,label,callback) {
 modal(`<h2 class="modal-heading" id="modal-title">${e(title)}</h2><p class="modal-subtitle">${e(message)}</p><div class="button-row"><button class="btn btn-dark" id="confirm-action">${e(label)}</button><button class="btn" data-action="close-modal">Keep things as they are</button></div>`);
 $('#confirm-action').addEventListener('click',async function(){
  this.disabled=true;
  try { await callback();if($('#modal').open)$('#modal').close(); }
  catch(err){toast(err.message,true);this.disabled=false;}
 });
}
function addressModal(a={}) {
 modal(`<h2 class="modal-heading" id="modal-title">${a.id?'A little change.':'A place to call home.'}</h2><form id="address-form" data-id="${a.id||''}">${errorBox()}${field('label','Address label',a.label||'',{min:1,max:40,placeholder:'Home, work…'})}${addressFields(a)}<button class="btn btn-dark btn-block" type="submit">Save address ${icon('check')}</button></form>`);
}
function productModal(p={}) {
 const images=[...new Map(state.adminProducts.map(x=>[x.image,x.name])).entries()];
 const specs=Object.entries(p.specs||{}).map(([k,v])=>`${k}: ${v}`).join('\n');
 modal(`<h2 class="modal-heading" id="modal-title">${p.id?'A little refinement.':'Something new for the edit.'}</h2><p class="modal-subtitle">${p.id?'Update product details, pricing and stock.':'Add a product using one of the bundled illustrations.'}</p><form id="admin-product-form" data-id="${p.id||''}">${errorBox()}${field('name','Product name',p.name||'',{min:2,max:100})}${field('slug','URL slug',p.slug||'',{min:2,max:100,pattern:'[a-z0-9]+(?:-[a-z0-9]+)*',placeholder:'e.g. halo-desk-lamp'})}${selectField('category','Category',state.config.categories,p.category||'')}<div class="form-row"><div class="field"><label for="product-price">Price · PKR</label><input id="product-price" type="number" min="1" max="10000000" step="1" name="price" required value="${p.price||''}"></div><div class="field"><label for="product-stock">Stock quantity</label><input id="product-stock" type="number" min="0" max="100000" step="1" name="stock" required value="${p.stock??25}"></div></div><div class="form-row">${field('compare_price','Original price',p.compare_price||'',{type:'number',required:false})}${field('badge','Badge',p.badge||'',{required:false,max:30,placeholder:'New arrival, Bestseller…'})}</div><div class="field"><label for="product-description">Description</label><textarea id="product-description" name="description" minlength="20" maxlength="3000" required>${e(p.description||'')}</textarea></div><div class="field"><label for="product-image">Catalogue illustration</label><select id="product-image" name="image" required>${images.map(([src,name])=>`<option value="${e(src)}" ${p.image===src?'selected':''}>${e(name)}</option>`).join('')}</select></div>${field('color','Finish colour',p.color||'#677361',{type:'color'})}<div class="field"><label for="product-specs">Specifications <span class="optional">(optional)</span></label><textarea id="product-specs" name="specs" rows="4" placeholder="Material: Oak&#10;Size: 20 × 10 cm">${e(specs)}</textarea><p class="fineprint">One detail per line: Label: Value. Up to 10 details.</p></div><div class="button-row" style="margin:20px 0"><label class="check-line"><input name="featured" type="checkbox" ${p.featured?'checked':''}>Feature on homepage</label><label class="check-line"><input name="active" type="checkbox" ${p.active!==false?'checked':''}>Visible in shop</label></div><button class="btn btn-dark btn-block" type="submit">${p.id?'Save changes':'Add product'} ${icon('check')}</button></form>`);
}
function displayFormError(form,err) {
 $$('.field-error',form).forEach(x=>x.remove());$$('[aria-invalid]',form).forEach(x=>x.removeAttribute('aria-invalid'));
 const box=$('.form-error',form);
 if (box) {box.hidden=false;box.textContent=err.message;box.setAttribute('tabindex','-1');box.focus({preventScroll:true});box.scrollIntoView({behavior:'smooth',block:'nearest'});}
 else toast(err.message,true);
 Object.entries(err.fields||{}).forEach(([name,message])=>{
  const input=form.elements.namedItem(name);if (!input||!input.closest) return;
  input.setAttribute('aria-invalid','true');
  const text=document.createElement('p');text.className='field-error';text.textContent=message;
  const id=`error-${name}-${Date.now()}`;text.id=id;input.setAttribute('aria-describedby',id);
  (input.closest('.field')||input.parentElement).append(text);
 });
}
function formObject(form) {return Object.fromEntries(new FormData(form));}
async function submitForm(form) {
 const data=formObject(form);
 switch(form.id) {
  case 'global-search': return navigate('/shop'+(data.q.trim()?'?q='+encodeURIComponent(data.q.trim()):''));
  case 'collection-search': {const params=new URLSearchParams(location.search);data.q.trim()?params.set('q',data.q.trim()):params.delete('q');return navigate('/shop?'+params);}
  case 'price-filter': {const params=new URLSearchParams(location.search);['min_price','max_price'].forEach(k=>data[k]?params.set(k,data[k]):params.delete(k));if(data.min_price&&data.max_price&&Number(data.min_price)>Number(data.max_price))throw new RequestError('The minimum price must be lower than the maximum price.');return navigate('/shop?'+params);}
  case 'newsletter-form': {const result=await api('/api/newsletter',{method:'POST',body:data});toast(result.message);form.reset();return;}
  case 'login-form':
  case 'register-form': {
   const registration=form.id==='register-form';if(registration)data.terms=form.elements.terms.checked;
   await api('/api/auth/'+(registration?'register':'login'),{method:'POST',body:data});await refreshSession();
   const next=new URLSearchParams(location.search).get('next');const safe=next&&next.startsWith('/')&&!next.startsWith('//');
   toast(registration?'Welcome to NorthStar. Make yourself at home.':'Good to have you back.');
   return navigate(safe?next:(state.user.role==='admin'?'/admin':'/account'),{replace:true});
  }
  case 'promo-form': {const result=await api('/api/cart/coupon',{method:'POST',body:data});state.cartCount=result.count;toast('A little extra good. Promo code applied.');return renderRoute(false);}
  case 'checkout-form': {
   const address=Object.fromEntries(['name','phone','line1','line2','city','postal_code'].map(k=>[k,data[k]]));
   const {order}=await api('/api/orders',{method:'POST',body:{address,note:data.note,payment_method:data.payment_method,terms:form.elements.terms.checked,idempotency_key:checkoutKey}});
   if(form.elements.save_address.checked) {
    try {await api('/api/addresses',{method:'POST',body:{...address,label:'Delivery address'}});}catch(err){toast('Your order is confirmed, but the address could not be saved.',true);}
   }
   state.cartCount=0;updateHeader();return navigate(`/orders/${order.number}?confirmed=1`,{replace:true});
  }
  case 'profile-form': {const result=await api('/api/profile',{method:'PATCH',body:data});state.user=result.user;updateHeader();toast('Your details have been updated.');return;}
  case 'password-form': {
   if(data.new_password!==data.confirm_password)throw new RequestError('Your new passwords do not match.',400,{confirm_password:'Enter the same new password in both fields.'});
   const result=await api('/api/profile/password',{method:'POST',body:data});form.reset();toast(result.message);return;
  }
  case 'address-form': {const id=form.dataset.id;await api('/api/addresses'+(id?'/'+id:''),{method:id?'PATCH':'POST',body:data});$('#modal').close();toast('Address saved. A little easier next time.');return renderRoute(false);}
  case 'support-form': {
   const result=await api('/api/support',{method:'POST',body:data});
   form.innerHTML=`<div class="form-success" role="status"><h3>You’re in good hands.</h3><p>Your message has been received. Keep this reference: <strong>${e(result.reference)}</strong>.</p><p>${state.user?'You can follow the reply in your support requests.':'Your message is saved in the shop inbox. This local website does not send email.'}</p>${state.user?'<a class="text-link" href="/account?tab=support" data-link>View your requests <span>↗</span></a>':'<a class="text-link" href="/shop" data-link>Back to the collection <span>↗</span></a>'}</div>`;return;
  }
  case 'admin-product-form': {
   data.price=Number(data.price);data.stock=Number(data.stock);data.compare_price=data.compare_price?Number(data.compare_price):null;
   data.featured=form.elements.featured.checked;data.active=form.elements.active.checked;
   const specs={};for(const line of data.specs.split('\n').filter(x=>x.trim())) {const index=line.indexOf(':');if(index<1||!line.slice(index+1).trim())throw new RequestError('Use “Label: Value” for each specification.');specs[line.slice(0,index).trim()]=line.slice(index+1).trim();}data.specs=specs;
   const id=form.dataset.id;await api('/api/admin/products'+(id?'/'+id:''),{method:id?'PATCH':'POST',body:data});$('#modal').close();toast(id?'The collection has been updated.':'A new piece has joined the collection.');return renderRoute(false);
  }
  case 'ticket-reply-form': {await api('/api/admin/tickets/'+form.dataset.id,{method:'PATCH',body:data});$('#modal').close();toast('Your response has been saved.');return renderRoute(false);}
 }
}
async function action(button) {
 const name=button.dataset.action,id=Number(button.dataset.id);
 if (name==='search-toggle') {const panel=$('#search-panel');panel.hidden=!panel.hidden;button.setAttribute('aria-expanded',String(!panel.hidden));if(!panel.hidden)$('#global-query').focus();return;}
 if (name==='menu') {const panel=$('#mobile-nav');panel.hidden=!panel.hidden;button.setAttribute('aria-expanded',String(!panel.hidden));return;}
 if (name==='close-modal') {$('#modal').close();return;}
 if (name==='retry') {return retryAction?.();}
 if (name==='show-password') {const input=$('input',button.parentElement);input.type=input.type==='password'?'text':'password';button.setAttribute('aria-label',input.type==='password'?'Show password':'Hide password');return;}
 if (name==='demo-login') {const admin=button.dataset.role==='admin';$('#login-form').elements.email.value=admin?'admin@northstar.local':'alex@northstar.local';$('#login-form').elements.password.value=admin?'NorthStarAdmin123!':'NorthStar123!';return;}
 if (name==='add') {
  const qty=button.dataset.detail?Number($('#detail-quantity').value):1;
  const cart=await api('/api/cart/items',{method:'POST',body:{product_id:id,quantity:qty}});state.cartCount=cart.count;updateHeader();toast('A good choice. Added to your bag.',false,'/cart');return;
 }
 if (name==='save') {
  if (!state.user) {toast('Sign in to keep your favourites.');return navigate('/login?next='+encodeURIComponent(location.pathname+location.search));}
  const saved=state.wishlist.includes(id);
  await api('/api/wishlist'+(saved?'/'+id:''),{method:saved?'DELETE':'POST',...(!saved?{body:{product_id:id}}:{})});
  state.wishlist=saved?state.wishlist.filter(x=>x!==id):[...state.wishlist,id];
  $$('[data-action="save"]').filter(x=>Number(x.dataset.id)===id).forEach(x=>{x.classList.toggle('is-saved',!saved);x.setAttribute('aria-pressed',String(!saved));x.setAttribute('aria-label',`${saved?'Save to':'Remove from'} wishlist`);});
  toast(saved?'Removed from your saved items.':'Saved for a little later.');
  if(location.pathname==='/wishlist'||location.pathname==='/account'&&location.search.includes('wishlist'))return renderRoute(false);return;
 }
 if (name==='quantity') {
  const input=$('input',button.closest('.quantity'));const value=Math.max(1,Math.min(Number(input.max),Number(input.value)+Number(button.dataset.step)));
  if(button.dataset.cartId){const cart=await api('/api/cart/items/'+button.dataset.cartId,{method:'PATCH',body:{quantity:value}});state.cartCount=cart.count;updateHeader();return renderRoute(false);}
  input.value=value;const buttons=$$('button',button.parentElement);buttons[0].disabled=value<=1;buttons[1].disabled=value>=Number(input.max);return;
 }
 if (name==='remove-cart') {const cart=await api('/api/cart/items/'+id,{method:'DELETE'});state.cartCount=cart.count;updateHeader();toast('Removed from your bag.');return renderRoute(false);}
 if (name==='remove-coupon') {await api('/api/cart/coupon',{method:'DELETE'});return renderRoute(false);}
 if (name==='logout') {await api('/api/auth/logout',{method:'POST'});await refreshSession();toast('You have been signed out. See you soon.');return navigate('/');}
 if (name==='new-address') return addressModal();
 if (name==='edit-address') return addressModal(state.addresses.find(x=>x.id===id));
 if (name==='delete-address') return confirmAction('Remove this address?','Your previous order details will stay as they are.','Remove address',async()=>{await api('/api/addresses/'+id,{method:'DELETE'});toast('Address removed.');await renderRoute(false);});
 if (name==='cancel-order') return confirmAction('A change of plan?','Your order will be cancelled and its stock released. You can always place a new order.','Cancel this order',async()=>{await api('/api/orders/'+button.dataset.number+'/cancel',{method:'POST'});toast('Your order has been cancelled.');await renderRoute(false);});
 if (name==='journal') {const story=stories[id];return modal(`<p class="eyebrow">THE JOURNAL / ${story.tag}</p><h2 class="modal-heading" id="modal-title">${story.title}</h2><div class="modal-body">${story.body}</div><a class="text-link" href="/shop" data-link>Discover your everyday <span>↗</span></a>`);}
 if (name==='new-product') return productModal();
 if (name==='edit-product') return productModal(state.adminProducts.find(x=>x.id===id));
 if (name==='archive-product') return confirmAction('Make a little room?','This piece will be removed from the shop and existing bags. Order history stays intact. You can restore it later.','Archive product',async()=>{await api('/api/admin/products/'+id,{method:'DELETE'});toast('Product archived.');await renderRoute(false);});
 if (name==='restore-product') {await api('/api/admin/products/'+id,{method:'PATCH',body:{active:true}});toast('Back in the collection.');return renderRoute(false);}
 if (name==='admin-order-detail') {const o=state.adminOrders.find(x=>x.number===button.dataset.number);if(!o)return;return modal(`<h2 class="modal-heading" id="modal-title">${e(o.number)}</h2><p class="modal-subtitle">${e(o.customer_name)} · ${e(o.customer_email)} · ${status(o.status)}</p>${orderBody(o,true)}`);}
 if (name==='update-order') {
  const number=button.dataset.number;const value=$('#status-'+number).value;
  return confirmAction(`Mark order ${value.toLowerCase()}?`,value==='Cancelled'?'This cancels the order and restores its stock.':'The customer will see this update in their order timeline.','Update order',async()=>{await api('/api/admin/orders/'+number,{method:'PATCH',body:{status:value}});toast('Order status updated.');await renderRoute(false);});
 }
 if (name==='reply-ticket') {const t=state.tickets.find(x=>x.id===id);return modal(`<h2 class="modal-heading" id="modal-title">A little human help.</h2><p class="modal-subtitle">${e(t.reference)} · ${e(t.subject)}</p><div class="info-box" style="margin-bottom:22px">${e(t.message)}</div><form id="ticket-reply-form" data-id="${id}">${errorBox()}<div class="field"><label for="ticket-response">Your response</label><textarea id="ticket-response" name="response" required minlength="5" maxlength="3000" rows="5">${e(t.response)}</textarea></div>${selectField('status','Status',['Open','Resolved'],t.status)}<p class="fineprint">Signed-in customers see this reply in their account. No email will be sent.</p><button class="btn btn-dark btn-block" type="submit">Save response ${icon('check')}</button></form>`);}
}

document.addEventListener('click',async event=>{
 const link=event.target.closest('a[data-link]');
 if(link&&!event.metaKey&&!event.ctrlKey&&!event.shiftKey&&!event.altKey&&event.button===0){event.preventDefault();return navigate(link.getAttribute('href'));}
 const button=event.target.closest('[data-action]');if(!button||button.disabled)return;
 event.preventDefault();
 const noBusy=['quantity','show-password','search-toggle','menu','close-modal'].includes(button.dataset.action);
 if(!noBusy)button.disabled=true;
 try{await action(button);}catch(err){toast(err.message,true);}finally{if(!noBusy&&button.isConnected)button.disabled=false;}
});
document.addEventListener('submit',async event=>{
 const form=event.target;if(!(form instanceof HTMLFormElement))return;event.preventDefault();
 if(form.dataset.busy==='true')return;
 if(!form.reportValidity())return;
 const button=$('button[type="submit"]',form)||$('button',form);const error=$('.form-error',form);if(error)error.hidden=true;
 $$('.field-error',form).forEach(x=>x.remove());$$('[aria-invalid]',form).forEach(x=>x.removeAttribute('aria-invalid'));
 if(button)button.disabled=true;form.dataset.busy='true';
 try{await submitForm(form);}catch(err){displayFormError(form,err);}finally{if(button?.isConnected)button.disabled=false;delete form.dataset.busy;}
});
document.addEventListener('change',event=>{
 const el=event.target;
 if(el.id==='sort-products'||el.id==='stock-filter') {const params=new URLSearchParams(location.search);if(el.id==='sort-products')params.set('sort',el.value);else el.checked?params.set('in_stock','1'):params.delete('in_stock');navigate('/shop?'+params);}
 if(el.id==='saved-address') {const a=state.addresses.find(x=>x.id===Number(el.value));$('#checkout-address-fields').innerHTML=addressFields(a||{});}
});
document.addEventListener('input',event=>{
 if(event.target.id==='admin-product-search') {const q=event.target.value.trim().toLowerCase();$('#admin-product-rows').innerHTML=adminProductRows(state.adminProducts.filter(p=>`${p.name} ${p.category} ${p.slug}`.toLowerCase().includes(q)));}
});
window.addEventListener('popstate',()=>{closePanels();renderRoute();});
document.addEventListener('keydown',event=>{if(event.key==='Escape')closePanels();});
$('#modal').addEventListener('click',event=>{if(event.target===$('#modal')){const r=$('#modal').getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)$('#modal').close();}});

async function init() {
 $('#search-toggle').innerHTML=icon('search');$('#wishlist-link').innerHTML=icon('heart');$('#account-link').innerHTML=icon('user');$('#bag-icon').innerHTML=icon('bag');$('#menu-toggle').innerHTML=icon('menu');
 try {
  await refreshSession();state.config=await api('/api/config');await renderRoute();
 } catch(err) {
  retryAction=init;$('#main').removeAttribute('aria-busy');$('#main').innerHTML=`<div class="container section">${empty('A little pause in the everyday.',err.message,{symbol:'return',url:'',label:'Try again',action:'retry'})}</div>`;
 }
}
init();
