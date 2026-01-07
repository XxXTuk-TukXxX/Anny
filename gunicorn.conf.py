import os

_DEFAULT_PORT = 8080

port_val = str(os.environ.get("PORT", str(_DEFAULT_PORT))).strip()
try:
    port = int(port_val)
except ValueError:
    port = _DEFAULT_PORT

bind = f"0.0.0.0:{port}"

# This app stores state and job progress in-process, so keep a single worker.
workers = 1
worker_class = "gthread"
threads = int(str(os.environ.get("GUNICORN_THREADS", "4")).strip() or "4")
timeout = int(str(os.environ.get("GUNICORN_TIMEOUT", "300")).strip() or "300")
