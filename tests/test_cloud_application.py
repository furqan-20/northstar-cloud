"""Meaningful regression checks for the WSGI and database adaptation."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from http.cookies import SimpleCookie

TEMP = tempfile.TemporaryDirectory()
os.environ['NORTHSTAR_DATA_DIR'] = TEMP.name
os.environ['NORTHSTAR_SEED_DEMO'] = '0'
os.environ['NORTHSTAR_REQUIRE_POSTGRES'] = '0'
os.environ['BUILD_REVISION'] = 'test-revision'
os.environ['NORTHSTAR_ADMIN_EMAIL'] = 'admin@test.example'
os.environ['NORTHSTAR_ADMIN_PASSWORD'] = 'Local-test-only-password-4821'

from database import connect, initialize
from wsgi import application


class Client:
    def __init__(self):
        self.cookie = ''
        self.csrf = ''

    def request(self, method, path, data=None, headers=None):
        route, _, query = path.partition('?')
        payload = json.dumps(data).encode() if data is not None else b''
        environ = {'REQUEST_METHOD': method, 'PATH_INFO': route, 'QUERY_STRING': query,
                   'wsgi.input': io.BytesIO(payload), 'REMOTE_ADDR': '127.0.0.1',
                   'SERVER_NAME': 'localhost', 'HTTP_HOST': 'localhost',
                   'CONTENT_LENGTH': str(len(payload)), 'CONTENT_TYPE': 'application/json',
                   'HTTP_COOKIE': self.cookie}
        if method not in ('GET', 'HEAD'):
            environ['HTTP_X_CSRF_TOKEN'] = self.csrf
        environ.update(headers or {})
        response = {}
        def start_response(status, response_headers):
            response['status'] = int(status.split()[0])
            response['headers'] = dict(response_headers)
        body = b''.join(application(environ, start_response))
        if 'Set-Cookie' in response['headers']:
            cookie = SimpleCookie(response['headers']['Set-Cookie'])
            self.cookie = '; '.join(f'{k}={v.value}' for k, v in cookie.items())
        if 'application/json' in response['headers'].get('Content-Type', '') and body:
            body = json.loads(body)
            if 'csrf_token' in body:
                self.csrf = body['csrf_token']
        return response['status'], body, response['headers']


class CloudApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize()

    def setUp(self):
        self.client = Client()
        self.client.request('GET', '/api/session')

    def register(self):
        import uuid
        email = uuid.uuid4().hex + '@test.example'
        status, body, _ = self.client.request('POST', '/api/auth/register',
            {'name': 'Cloud Tester', 'email': email, 'password': 'Test-password-9381', 'terms': True})
        self.assertEqual(status, 201, body)
        return email

    def test_health_reports_build_and_database(self):
        status, body, _ = self.client.request('GET', '/healthz')
        self.assertEqual(status, 200)
        self.assertEqual(body['revision'], 'test-revision')

    def test_home_static_asset_and_unknown_route(self):
        for route in ('/', '/shop', '/static/js/app.js'):
            self.assertEqual(self.client.request('GET', route)[0], 200)
        self.assertEqual(self.client.request('GET', '/unknown-route')[0], 404)
        self.assertEqual(self.client.request('GET', '/static/../database.py')[0], 404)

    def test_search_is_case_insensitive_and_literal(self):
        status, body, _ = self.client.request('GET', '/api/products?q=HALO')
        self.assertEqual(status, 200)
        self.assertTrue(any(p['slug'] == 'halo-desk-lamp' for p in body['products']))
        _, body, _ = self.client.request('GET', '/api/products?q=%25')
        self.assertEqual(body['total'], 0)
        self.assertEqual(self.client.request('GET', '/api/products?sort=name')[0], 200)

    def test_cross_origin_and_missing_csrf_are_rejected(self):
        status, _, _ = self.client.request('POST', '/api/newsletter', {'email': 'x@test.example'},
                                          {'HTTP_X_CSRF_TOKEN': ''})
        self.assertEqual(status, 403)
        status, _, _ = self.client.request('POST', '/api/newsletter', {'email': 'x@test.example'},
                                          {'HTTP_ORIGIN': 'https://different.example'})
        self.assertEqual(status, 403)

    def test_registration_login_and_duplicate_rejection(self):
        email = self.register()
        self.client.request('POST', '/api/auth/logout', {})
        status, body, _ = self.client.request('POST', '/api/auth/login',
            {'email': email.upper(), 'password': 'Test-password-9381'})
        self.assertEqual(status, 200, body)
        status, _, _ = self.client.request('POST', '/api/auth/register',
            {'name': 'Again', 'email': email, 'password': 'Test-password-9381', 'terms': True})
        self.assertEqual(status, 409)

    def test_address_crud_and_ownership(self):
        self.register()
        address = {'label': 'Home', 'name': 'Cloud Tester', 'phone': '03001234567',
                   'line1': 'Test address 123', 'line2': '', 'city': 'Karachi', 'postal_code': '75300'}
        status, body, _ = self.client.request('POST', '/api/addresses', address)
        self.assertEqual(status, 201, body)
        _, body, _ = self.client.request('GET', '/api/addresses')
        aid = body['addresses'][0]['id']
        other = Client()
        other.request('GET', '/api/session')
        self.assertEqual(other.request('GET', '/api/addresses')[0], 401)
        address['label'] = 'Office'
        self.assertEqual(self.client.request('PATCH', f'/api/addresses/{aid}', address)[0], 200)
        self.assertEqual(self.client.request('DELETE', f'/api/addresses/{aid}')[0], 200)

    def test_order_idempotency_and_stock_restoration(self):
        import uuid
        self.register()
        _, catalogue, _ = self.client.request('GET', '/api/products')
        product = next(p for p in catalogue['products'] if p['slug'] == 'daily-stoneware-mug')
        stock = product['stock']
        self.assertEqual(self.client.request('POST', '/api/cart/items',
            {'product_id': product['id'], 'quantity': 2})[0], 201)
        order = {'idempotency_key': uuid.uuid4().hex, 'payment_method': 'cod', 'terms': True,
                 'address': {'name': 'Cloud Tester', 'phone': '03001234567', 'line1': 'Test address 123',
                             'line2': '', 'city': 'Karachi', 'postal_code': '75300'}}
        status, body, _ = self.client.request('POST', '/api/orders', order)
        self.assertEqual(status, 201, body)
        number = body['order']['number']
        self.assertEqual(body['order']['total'], 3950)
        _, repeated, _ = self.client.request('POST', '/api/orders', order)
        self.assertEqual(repeated['order']['number'], number)
        _, changed, _ = self.client.request('GET', '/api/products/daily-stoneware-mug')
        self.assertEqual(changed['product']['stock'], stock - 2)
        self.assertEqual(self.client.request('POST', f'/api/orders/{number}/cancel', {})[0], 200)
        self.assertEqual(self.client.request('POST', f'/api/orders/{number}/cancel', {})[0], 409)
        _, changed, _ = self.client.request('GET', '/api/products/daily-stoneware-mug')
        self.assertEqual(changed['product']['stock'], stock)

    def test_seed_initialization_is_idempotent_and_demo_accounts_absent(self):
        initialize()
        db = connect()
        try:
            self.assertIsNone(db.execute('SELECT 1 FROM users WHERE email=?', ('admin@northstar.local',)).fetchone())
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0], 1)
        finally:
            db.close()

    def test_cookie_flags_and_head_response(self):
        client = Client()
        _, _, headers = client.request('GET', '/api/session')
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Lax', headers['Set-Cookie'])
        status, body, _ = client.request('HEAD', '/api/products')
        self.assertEqual(status, 200)
        self.assertEqual(body, b'')

    def test_newsletter_duplicate_and_admin_authorization(self):
        for _ in range(2):
            self.assertEqual(self.client.request('POST', '/api/newsletter',
                {'email': 'subscriber@test.example'})[0], 201)
        self.assertEqual(self.client.request('GET', '/api/admin/overview')[0], 401)
        status, body, _ = self.client.request('POST', '/api/auth/login',
            {'email': 'admin@test.example', 'password': 'Local-test-only-password-4821'})
        self.assertEqual(status, 200, body)
        self.assertEqual(self.client.request('GET', '/api/admin/overview')[0], 200)


if __name__ == '__main__':
    unittest.main()
