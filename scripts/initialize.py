"""Idempotent schema initialization; cloud credentials are supplied through the environment."""
from database import initialize

if __name__ == '__main__':
    initialize()
    print('NorthStar database schema and catalogue are ready.', flush=True)
