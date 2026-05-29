#!/bin/bash
# setup.sh — full environment setup for the Sole Django project
# Run from inside the sole/ directory: bash setup.sh

set -e  # exit on any error

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"   # sole/ directory
ENV_DIR="$BASE_DIR/../env"                  # backend/env/

echo ""
echo "=== Sole — Environment Setup ==="
echo "Project dir : $BASE_DIR"
echo "Venv dir    : $ENV_DIR"
echo ""

# ── Step 1: create venv if it doesn't exist ──────────────────────────────────
if [ ! -d "$ENV_DIR" ]; then
    echo "[1/6] Creating virtual environment..."
    python3 -m venv "$ENV_DIR"
else
    echo "[1/6] Virtual environment already exists — skipping creation."
fi

PIP="$ENV_DIR/bin/pip"
PYTHON="$ENV_DIR/bin/python3"

# ── Step 2: upgrade pip ───────────────────────────────────────────────────────
echo ""
echo "[2/6] Upgrading pip..."
"$PYTHON" -m pip install --upgrade pip --quiet

# ── Step 3: install core packages ────────────────────────────────────────────
echo ""
echo "[3/6] Installing core packages..."
"$PIP" install \
    django \
    djangorestframework \
    curl-cffi \
    beautifulsoup4 \
    lxml \
    orjson \
    cssselect \
    tldextract \
    w3lib \
    --quiet

echo "    ✓ django, djangorestframework, curl-cffi, beautifulsoup4, lxml, orjson"

# ── Step 4: install scrapling (no deps) + patch broken __init__ ──────────────
# scrapling depends on camoufox which requires pyobjc-core (needs C compiler
# on macOS). We install scrapling without its optional deps and patch its
# __init__.py so the Adaptor (CSS selector engine) is importable without
# triggering the broken camoufox import.
echo ""
echo "[4/6] Installing scrapling and patching for macOS compatibility..."

"$PIP" install "scrapling==0.2.9" --no-deps --quiet

SCRAPLING_INIT="$ENV_DIR/lib/python$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')/site-packages/scrapling/__init__.py"

cat > "$SCRAPLING_INIT" << 'SCRAPLING_PATCH'
# Patched: camoufox/pyobjc-core unavailable on this env — skip fetchers,
# expose only Adaptor (the CSS/XPath parser which has no native deps).
from scrapling.core.custom_types import AttributesHandler, TextHandler
from scrapling.parser import Adaptor, Adaptors
try:
    from scrapling.fetchers import (AsyncFetcher, CustomFetcher, Fetcher,
                                    PlayWrightFetcher, StealthyFetcher)
except Exception:
    pass
__version__ = "0.2.9"
__all__ = ['Adaptor', 'Adaptors']
SCRAPLING_PATCH

echo "    ✓ scrapling installed and patched"

# ── Step 5: install Playwright + download Chromium ───────────────────────────
echo ""
echo "[5/6] Installing Playwright and downloading Chromium..."

"$PIP" install playwright --quiet
"$ENV_DIR/bin/playwright" install chromium

echo "    ✓ playwright + chromium ready"

# ── Step 6: run Django migrations ────────────────────────────────────────────
echo ""
echo "[6/6] Running Django migrations..."

cd "$BASE_DIR"
"$PYTHON" manage.py migrate --run-syncdb

echo ""
echo "============================================"
echo " Setup complete."
echo ""
echo " Activate the environment:"
echo "   source env/bin/activate"
echo ""
echo " Start the server:"
echo "   cd sole"
echo "   ../env/bin/python3 manage.py runserver"
echo ""
echo " API endpoint:"
echo "   POST http://127.0.0.1:8000/api/scrape/"
echo '   Body: {"url": "https://..."}'
echo "============================================"
echo ""
