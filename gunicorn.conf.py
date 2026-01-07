import os

_DEFAULT_PORT = 8080

port_val = str(os.environ.get("PORT", str(_DEFAULT_PORT))).strip()
try:
    port = int(port_val)
except ValueError:
    port = _DEFAULT_PORT

bind = f"0.0.0.0:{port}"
