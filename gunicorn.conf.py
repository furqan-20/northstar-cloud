import os

bind = '0.0.0.0:8000'
workers = int(os.environ.get('WEB_CONCURRENCY', '2'))
threads = int(os.environ.get('WEB_THREADS', '2'))
worker_class = 'gthread'
timeout = 60
graceful_timeout = 30
keepalive = 5
accesslog = '-'
errorlog = '-'
capture_output = True
forwarded_allow_ips = '127.0.0.1'
limit_request_line = 4094
limit_request_fields = 50
limit_request_field_size = 8190
