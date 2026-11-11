#!/usr/bin/env python3
"""Run all regressions with network access blocked and optional randomized order."""
import argparse
from pathlib import Path
import random
import socket
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shuffle-seed',type=int)
    args=parser.parse_args()
    attempts=[]
    def blocked(*unused,**kwargs):
        attempts.append('network attempt blocked')
        raise AssertionError('Offline regression attempted a network connection')
    socket.socket.connect=blocked
    socket.socket.connect_ex=blocked
    socket.create_connection=blocked
    class Order:
        def pytest_collection_modifyitems(self,items):
            if args.shuffle_seed is not None:random.Random(args.shuffle_seed).shuffle(items)
    result=pytest.main(['-q',str(ROOT/'tests')],plugins=[Order()])
    print(f'Network attempts: {len(attempts)}; shuffle seed: {args.shuffle_seed}')
    return int(result) if result else int(bool(attempts))


if __name__=='__main__':raise SystemExit(main())
