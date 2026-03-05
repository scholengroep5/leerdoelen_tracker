#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# Flask-Migrate helper
# Gebruik: ./migrate.sh [init|migrate|upgrade|history|current]
#
# Draait de migratie commando's BINNEN de backend container.
# Zorg dat de containers draaien: docker compose up -d
# ══════════════════════════════════════════════════════════════════════════════

CONTAINER="leerdoelen_backend"
CMD=${1:-upgrade}
MSG=${2:-"auto migration"}

case "$CMD" in
  init)
    echo "→ Initialiseer migrations/ map (eenmalig)"
    docker exec $CONTAINER flask db init
    ;;
  migrate)
    echo "→ Genereer nieuwe migratie: '$MSG'"
    docker exec $CONTAINER flask db migrate -m "$MSG"
    echo ""
    echo "⚠ Controleer de gegenereerde migratie in migrations/versions/ voor je upgrade!"
    ;;
  upgrade)
    echo "→ Voer alle openstaande migraties uit"
    docker exec $CONTAINER flask db upgrade
    ;;
  downgrade)
    echo "→ Zet één stap terug"
    docker exec $CONTAINER flask db downgrade
    ;;
  history)
    docker exec $CONTAINER flask db history
    ;;
  current)
    docker exec $CONTAINER flask db current
    ;;
  *)
    echo "Gebruik: ./migrate.sh [init|migrate 'beschrijving'|upgrade|downgrade|history|current]"
    exit 1
    ;;
esac
