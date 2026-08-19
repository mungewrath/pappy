"""Lambda entrypoint. Only engaged when running under AWS Lambda.

Local development runs `pappy.api.app:app` directly under uvicorn instead —
see README.md.
"""

from __future__ import annotations

from mangum import Mangum

from pappy.api.app import app

handler = Mangum(app)
