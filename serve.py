"""Production entry point for the Paw Patrol app.

Runs the same Flask app with Waitress (a production server) instead of
Flask's built-in development server, so the "This is a development server"
warning goes away.

    python3 serve.py                 # http://localhost:5000
    PORT=5001 python3 serve.py       # different port (e.g. while testing)

Why one process with threads: the dog connections, the emergency-stop flag
and the running patrol live in memory inside the app, so it must stay a
single process. Threads let it serve many requests and live streams at once.
"""

import logging
import os

from waitress import serve

from app import app

HOST = os.environ.get("HOST", "0.0.0.0")      # 0.0.0.0 = reachable from other devices on the network
PORT = int(os.environ.get("PORT", "5000"))
THREADS = int(os.environ.get("THREADS", "16"))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(f"Paw Patrol running at http://localhost:{PORT}")
    serve(
        app,
        host=HOST,
        port=PORT,
        threads=THREADS,
        channel_timeout=3600,   # keep long live streams (patrols, analysis) open
    )