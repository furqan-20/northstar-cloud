"""Serve the existing NorthStar routes behind Gunicorn without a development HTTP server."""
from email.message import Message
from http import HTTPStatus
import io
import json
import os
from urllib.parse import quote

from database import connect
from server import Handler


class WSGIHandler(Handler):
    """Adapt an already-parsed WSGI request to the existing business handlers."""

    def __init__(self, environ):
        self.command = environ['REQUEST_METHOD']
        self.path = quote(environ.get('PATH_INFO', '/'), safe='/')
        if environ.get('QUERY_STRING'):
            self.path += '?' + environ['QUERY_STRING']
        self.headers = Message()
        for name, value in environ.items():
            if name.startswith('HTTP_'):
                self.headers[name[5:].replace('_', '-')] = str(value)
        for name in ('CONTENT_TYPE', 'CONTENT_LENGTH'):
            if environ.get(name):
                self.headers[name.replace('_', '-')] = str(environ[name])
        if 'Host' not in self.headers:
            self.headers['Host'] = environ.get('SERVER_NAME', 'localhost')
        self.client_address = (environ.get('REMOTE_ADDR', '127.0.0.1'), 0)
        self.rfile = environ['wsgi.input']
        self.wfile = io.BytesIO()
        self.status = 200
        self.response_headers = []

    def send_response(self, status, message=None):
        self.status = status

    def send_header(self, name, value):
        self.response_headers.append((str(name), str(value)))

    def end_headers(self):
        pass


def application(environ, start_response):
    if environ.get('PATH_INFO') == '/healthz':
        status = 200
        try:
            db = connect()
            try:
                db.execute('SELECT 1 FROM products LIMIT 1').fetchone()
            finally:
                db.close()
            result = {'status': 'ok', 'revision': os.environ.get('BUILD_REVISION', 'development'),
                      'instance': os.environ.get('HOSTNAME', 'local')}
        except Exception:
            status = 503
            result = {'status': 'unavailable'}
        body = json.dumps(result).encode()
        start_response(f'{status} {HTTPStatus(status).phrase}',
                       [('Content-Type', 'application/json'), ('Cache-Control', 'no-store'),
                        ('Content-Length', str(len(body)))])
        return [b'' if environ['REQUEST_METHOD'] == 'HEAD' else body]

    handler = WSGIHandler(environ)
    handler.dispatch()
    start_response(f'{handler.status} {HTTPStatus(handler.status).phrase}', handler.response_headers)
    return [handler.wfile.getvalue()]
