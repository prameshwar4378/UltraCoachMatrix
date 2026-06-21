"""
Automatic settings selector for UltraCoachMatrix.

Local machines use development settings by default. The VPS uses production
settings automatically when DJANGO_ENV=production, when the project is placed
under /var/www, or when the server hostname follows the vmi* VPS pattern.
"""

import os
import socket
import sys
from pathlib import Path


def _running_on_vps():
    project_root = Path(__file__).resolve().parents[1]
    hostname = socket.gethostname().lower()
    project_parts = {part.lower() for part in project_root.parts}

    return (
        hostname.startswith("vmi")
        or "var" in project_parts and "www" in project_parts
    )


def _selected_environment():
    explicit_env = os.environ.get("DJANGO_ENV", "").strip().lower()
    if explicit_env in {"production", "prod", "live"}:
        return "production"
    if explicit_env in {"development", "dev", "local"}:
        return "development"
    if "test" in sys.argv:
        return "development"
    return "production" if _running_on_vps() else "development"


ENVIRONMENT = _selected_environment()

if ENVIRONMENT == "production":
    from .settings_production import *  # noqa: F401,F403
else:
    from .settings_development import *  # noqa: F401,F403
