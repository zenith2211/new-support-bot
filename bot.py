#!/usr/bin/env python3
"""
Entry point.

    python bot.py

Configuration comes from environment variables only — copy .env.example and
fill it in, or set the same variables in your host's dashboard.
"""

from app.runner import run

if __name__ == "__main__":
    run()
