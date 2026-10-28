"""Unit and geometry tests never spend API credits or depend on venue Wi-Fi."""
import os

for key in ("META_API_KEY", "BASETEN_API_KEY", "FIREWORKS_API_KEY"):
    os.environ[key] = ""
