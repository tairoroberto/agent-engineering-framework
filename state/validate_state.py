#!/usr/bin/env python3
"""Compatibility entry point for portable state validation."""

import sys

from state import main


if __name__ == "__main__":
    sys.argv = [sys.argv[0], "validate", *sys.argv[1:]]
    main()
