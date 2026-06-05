#!/usr/bin/env python3
"""Compatibility entrypoint for the terminal app.

The real terminal implementation lives in terminal/archer.py.
"""

import sys
from terminal import archer as _impl

sys.modules[__name__] = _impl

if __name__ == "__main__":
    _impl.run()
