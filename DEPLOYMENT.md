# Deployment handleiding

De CI/CD pipeline **bouwt enkel de Docker image** en zet die in de container registry.  
Hoe je die image daarna uitrolt op jouw server is volledig aan jou — hieronder staan de meest gebruikte opties.

---

## Stap 1 — Repo instellen in Gitea

Ga naar **Settings → Actions** van jouw fork/kopie van deze repo en stel in:

### Variables  
*(Settings → Actions → Variables)*

| Naam | Beschrijving | Voorbeeld |
|------|-------------|---------|
| `REGISTRY` | Hostname van jouw container registry | `gitea.jouwdomein.be` of `ghcr.io` |
| `IMAGE_NAME` | Volledig pad van de image (zonder tag) | `gitea.jouwdomein.be/scholengroep5/leerdoelen-tracker` |

### Secrets  
*(Settings → Actions → Secrets)*

| Naam | Beschrijving |
|------|-------------|
| `REGISTRY_USER` | Gebruikersnaam voor de registry |
| `REGISTRY_TOKEN` | Wachtwoord of access token |

> **Gitea ingebouwde registry:** maak een Gitea access token aan via  
> *User Settings → Applications → Generate Token* (scope: `package:write`)

---

## Stap 2 — Server voorbereiden

### `.env` aanmaken op de server

Kopieer `.env.example` naar `.env` en vul alle waarden in:

```bash
cp .env.example .env
nano .env
```

### `docker-compose.yml` aanpassen

Vervang de `build:` sectie van de backend door een `image:` verwijzing naar jouw registry:

```yaml
services:
  backend:
    image: gitea.jouwdomein.be/scholengroep5/leerdoelen-tracker:latest
    # build: ./backend   ← deze regel weghalen of uitcommentariëren
    restart: unless-stopped
    ...
```

---

## Stap 3 — Deployment opties

### Optie A — Handmatig (eenvoudigst)

Na elke nieuwe build in Gitea voer je dit uit op je server:

```bash
cd /pad/naar/leerdoelen
docker compose pull backend
docker compose up -d --no-deps backend
docker image prune -f
```

### Optie B — Watchtower (automatisch)

[Watchtower](https://containrrr.dev/watchtower/) controleert periodiek of er nieuwe images zijn en herstart containers automatisch.

```yaml
# Voeg toe aan je docker-compose.yml
  watchtower:
    image: containrrr/watchtower
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /root/.docker/config.json:/config.json   # voor private registry auth
    command: --interval 300 --cleanup backend    # elke 5 min, enkel backend container
    environment:
      - WATCHTOWER_POLL_INTERVAL=300
```

Zorg dat Docker op de server ingelogd is op jouw registry:
```bash
docker login gitea.jouwdomein.be -u jouw-user
```

### Optie C — Portainer webhook

Als je Portainer gebruikt:
1. Ga naar jouw stack → **Webhooks**
2. Kopieer de webhook URL
3. Voeg in Gitea een **webhook** toe onder *Settings → Webhooks*  
   → URL = jouw Portainer webhook, trigger = **push**

Portainer pulled dan automatisch de nieuwe image en herstart de service.

### Optie D — Gitea runner met SSH (zelf te schrijven)

Als je toch een geautomatiseerde SSH-deploy wil, maak dan een **aparte workflow** in jouw eigen fork — niet in de gedeelde repo. Voorbeeld:

```yaml
# .gitea/workflows/deploy.yml  — enkel in JOUW fork, niet in de gedeelde repo
name: Deploy naar onze VPS
on:
  workflow_run:
    workflows: ["Build & Push"]
    types: [completed]

jobs:
  deploy:
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    runs-on: ubuntu-latest
    steps:
      - name: SSH deploy
        uses: appleboy/ssh-action@v1
        with:
          host:     ${{ secrets.DEPLOY_HOST }}
          username: ${{ secrets.DEPLOY_USER }}
          key:      ${{ secrets.DEPLOY_SSH_KEY }}
          script: |
            cd /pad/naar/leerdoelen
            docker compose pull backend
            docker compose up -d --no-deps backend
            docker image prune -f
```

---

## Updates installeren

```bash
# Image pullen en backend herstarten (downtime < 1 seconde)
docker compose pull backend && docker compose up -d --no-deps backend

# Eventuele database migraties worden automatisch uitgevoerd bij het opstarten
# (zie entrypoint.sh — flask db upgrade)
```

## Rollback

Elke build krijgt ook een `sha-XXXXXXXX` tag. Rollback naar een vorige versie:

```bash
# Vervang sha-tag door de gewenste commit hash
docker compose stop backend
docker compose run --rm -e IMAGE_TAG=sha-a1b2c3d4 backend echo ok
# Of pas IMAGE_NAME in je .env tijdelijk aan naar de sha-tag
```
