"""Exercise the actual HTTP service; save small machine-readable results, not screenshots."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import http.cookiejar
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid


class Client:
    def __init__(self, base):
        self.base = base.rstrip('/')
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = ''

    def request(self, path, method='GET', data=None, headers=None):
        payload = json.dumps(data).encode() if data is not None else None
        request_headers = {'Accept': 'application/json'}
        if data is not None:
            request_headers['Content-Type'] = 'application/json'
        if method not in ('GET', 'HEAD'):
            request_headers['X-CSRF-Token'] = self.csrf
        request_headers.update(headers or {})
        request = urllib.request.Request(self.base + path, data=payload,
                                         headers=request_headers, method=method)
        try:
            response = self.opener.open(request, timeout=30)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            body = response.read()
            if 'application/json' in response.headers.get('Content-Type', '') and body:
                body = json.loads(body)
                self.csrf = body.get('csrf_token', self.csrf)
            return response.status, body


def run(base, revision='', full=False):
    client = Client(base)
    results = []

    def check(name, function):
        started = time.perf_counter()
        function()
        results.append({'check': name, 'status': 'passed',
                        'duration_ms': round((time.perf_counter() - started) * 1000, 2)})
        print('PASS:', name, flush=True)

    def health():
        status, body = client.request('/healthz')
        assert status == 200 and body['status'] == 'ok', (status, body)
        if revision:
            assert body['revision'] == revision, body
    check('Database readiness and expected deployed revision', health)

    def home():
        status, body = client.request('/')
        assert status == 200 and b'NORTHSTAR' in body
        assert client.request('/static/js/app.js')[0] == 200
    check('Website and JavaScript asset are accessible', home)

    def search():
        status, body = client.request('/api/products?q=HALO')
        assert status == 200 and any(p['slug'] == 'halo-desk-lamp' for p in body['products'])
    check('Case-insensitive catalogue search', search)
    if not full:
        return results

    client.request('/api/session')
    email = 'ci-' + uuid.uuid4().hex + '@test.example'
    password = 'Temporary-test-' + uuid.uuid4().hex

    def csrf_rejected():
        status, _ = client.request('/api/newsletter', 'POST', {'email': email}, {'X-CSRF-Token': ''})
        assert status == 403, status
    check('Missing CSRF token is rejected', csrf_rejected)

    def register():
        status, body = client.request('/api/auth/register', 'POST',
            {'name': 'CI Test Customer', 'email': email, 'password': password, 'terms': True})
        assert status == 201 and body['user']['email'] == email, (status, body)
    check('Customer registration and authenticated session', register)

    def session_shared():
        for _ in range(8):
            status, body = client.request('/api/session')
            assert status == 200 and body['user']['email'] == email, (status, body)
    check('Authenticated session persists across repeated requests', session_shared)

    status, products = client.request('/api/products?q=daily%20stoneware')
    assert status == 200 and products['products']
    product = products['products'][0]

    def cart():
        status, body = client.request('/api/cart/items', 'POST',
                                      {'product_id': product['id'], 'quantity': 2})
        assert status == 201 and body['total'] == 3950, (status, body)
    check('Cart quantities and delivery total', cart)

    address = {'label': 'Home', 'name': 'CI Test Customer', 'phone': '03001234567',
               'line1': 'Demonstration address 123', 'line2': '', 'city': 'Karachi', 'postal_code': '75300'}

    def address_crud():
        status, body = client.request('/api/addresses', 'POST', address)
        assert status == 201, (status, body)
        _, body = client.request('/api/addresses')
        aid = body['addresses'][0]['id']
        assert client.request(f'/api/addresses/{aid}', 'PATCH', dict(address, label='Office'))[0] == 200
        assert client.request(f'/api/addresses/{aid}', 'DELETE')[0] == 200
    check('Saved address create, read, update and delete', address_crud)

    def order():
        payload = {'idempotency_key': uuid.uuid4().hex, 'payment_method': 'cod',
                   'terms': True, 'address': address}
        status, body = client.request('/api/orders', 'POST', payload)
        assert status == 201, (status, body)
        number = body['order']['number']
        _, second = client.request('/api/orders', 'POST', payload)
        assert second['order']['number'] == number, second
        assert client.request(f'/api/orders/{number}/cancel', 'POST', {})[0] == 200
    check('Order persistence, idempotency and cancellation', order)

    def support():
        status, body = client.request('/api/support', 'POST',
            {'name': 'CI Test Customer', 'email': email, 'subject': 'Cloud build verification',
             'message': 'This is an automated check against an ephemeral CI database.'})
        assert status == 201 and body['reference'].startswith('NSH-'), (status, body)
        assert client.request('/api/support')[0] == 200
    check('Support message is saved and can be retrieved', support)

    def login():
        assert client.request('/api/auth/logout', 'POST', {})[0] == 200
        status, _ = client.request('/api/auth/login', 'POST', {'email': email, 'password': 'wrong-password'})
        assert status == 401, status
        assert client.request('/api/auth/login', 'POST', {'email': email, 'password': password})[0] == 200
    check('Logout, invalid login rejection and valid login', login)

    def multi_worker_health():
        def get_one(_):
            return Client(base).request('/healthz')
        with ThreadPoolExecutor(max_workers=6) as executor:
            samples = list(executor.map(get_one, range(16)))
        assert all(status == 200 for status, _ in samples)
        instances = sorted({body['instance'] for _, body in samples})
        if len(instances) < 2:
            raise AssertionError(f'Expected two CI application containers; observed {instances}')
        print('Verified application containers:', ', '.join(instances), flush=True)
    check('Two application containers are reachable through Nginx', multi_worker_health)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--revision', default='')
    parser.add_argument('--full', action='store_true', help='Writes disposable test data; use only in CI.')
    parser.add_argument('--output', default='cloud-build-results.json')
    args = parser.parse_args()
    started = datetime.now(timezone.utc).isoformat()
    try:
        results = run(args.url, args.revision, args.full)
    except Exception as exc:
        Path(args.output).write_text(json.dumps({'started_utc': started, 'status': 'failed',
                                                'error': str(exc)}, indent=2))
        raise
    Path(args.output).write_text(json.dumps({'started_utc': started, 'status': 'passed',
                                            'revision': args.revision, 'checks': results}, indent=2))


if __name__ == '__main__':
    main()
