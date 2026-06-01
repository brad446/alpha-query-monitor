#!/usr/bin/env python3
"""Entry point — copy .env.example to .env, fill in credentials, then: python run.py"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from kalshi_btc_algo.main import main

if __name__ == "__main__":
    main()
