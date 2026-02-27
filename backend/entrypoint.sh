#!/bin/bash
set -e

echo "→ Flask-Migrate: database upgraden naar laatste versie..."
flask db upgrade

echo "→ App starten..."
exec "$@"
