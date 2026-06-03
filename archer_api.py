#!/usr/bin/env python3
"""Compatibility entrypoint for the desktop API.

The real API implementation lives in terminal/archer_api.py.
"""

import sys
from terminal import archer_api as _impl

sys.modules[__name__] = _impl

if __name__ == "__main__":
    _impl.main()
