#!/usr/bin/env python3
"""Back up the local data directory and restore the original demonstration data."""
import argparse
from datetime import datetime
from database import DATA, initialize

def main():
    parser=argparse.ArgumentParser(description='Back up NorthStar data and restore the starting catalogue/accounts. Stop the server first.')
    parser.add_argument('--yes', action='store_true', help='Confirm the reset without an interactive prompt.')
    args=parser.parse_args()
    print('Stop every running NorthStar server before resetting data.')
    if not args.yes and input('Back up existing data and start fresh? Type RESET: ').strip()!='RESET':
        print('No changes made.');return
    if DATA.exists():
        backup=DATA.with_name(DATA.name+'-backup-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        DATA.rename(backup)
        print(f'Previous data kept at: {backup}')
    initialize()
    print('Starting catalogue and demo accounts restored. Run python3 server.py to start NorthStar.')

if __name__=='__main__': main()
