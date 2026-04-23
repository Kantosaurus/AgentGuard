"""Make the ``app.*`` package importable from inside ``tests/`` regardless of
working directory. The control_plane image sets WORKDIR=/app, so that already
works inside docker; this shim keeps ``pytest`` green when the suite is run
from the repo root without ``cd``."""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_CP = os.path.dirname(_HERE)  # .../demo/control_plane
if _CP not in sys.path:
    sys.path.insert(0, _CP)
