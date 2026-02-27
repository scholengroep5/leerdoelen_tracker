# Leerdoelen Tracker

Leerdoelen-opvolgsysteem voor GO! scholengroepen.

## Rollenstructuur

| Rol | Wat kan die? |
|---|---|
| `superadmin` | Platformbeheer, scholengroep ICT aanwijzen |
| `scholengroep_ict` | Scholen aanmaken, school ICT en directeurs toewijzen |
| `school_ict` | Leerkrachten en klassen van eigen school beheren |
| `director` | Overzicht van eigen school raadplegen |
| `teacher` | Leerdoelen invullen |

Alle gebruikers (behalve superadmin) loggen in via **Microsoft Entra ID**.

---

## Snelle start

```bash
# 1. Configuratie
cp .env.example .env
# Vul POSTGRES_PASSWORD, SECRET_KEY, BASE_URL en Entra gegevens in

# 2. JSON doelen klaarzetten
#    Voer converteer_doelen.py uit en kopieer de doelen/ map hier

# 3. Opstarten
docker compose up -d

# 4. Superadmin wachtwoord instellen
# Ga naar http://localhost/auth/setup
```

---

## Entra ID configureren

1. Ga naar https://portal.azure.com → **App registrations** → **New registration**
2. Naam: `Leerdoelen Tracker`
3. **Supported account types**: kies **"Accounts in any organizational directory (Any Microsoft Entra ID tenant - Multitenant)"**
   - Dit is cruciaal! Elke school heeft een eigen tenant.
4. **Redirect URI**: `https://jouwdomain.be/auth/callback`
5. Na aanmaken → **Certificates & secrets** → nieuwe client secret aanmaken
6. Kopieer **Application (client) ID** en de secret naar `.env`

### Benodigde API permissions
- `openid` (ingebouwd)
- `profile` (ingebouwd)
- `email` (ingebouwd)
- `User.Read` (Microsoft Graph)

---

## Opstartflow voor een nieuwe scholengroep

### Stap 1: Superadmin setup (eenmalig)
```
http://jouwdomain.be/auth/setup
→ Stel wachtwoord in voor admin@leerdoelen.local
```

### Stap 2: Scholengroep ICT toevoegen (superadmin)
```
Dashboard → Scholengroep ICT → Toevoegen
→ Vul Microsoft e-mailadres in van de ICT-medewerker
→ Zij loggen in via "Inloggen met Microsoft" en krijgen automatisch de juiste rol
```

### Stap 3: Scholen aanmaken (scholengroep ICT)
```
Dashboard → School toevoegen
→ Naam: "Basisschool De Krekel"
→ E-maildomeinen: "dekrekel.be" (optioneel, voor automatische koppeling)
```

### Stap 4: Directeur/School ICT toevoegen (scholengroep ICT)
```
Dashboard → Gebruiker toevoegen
→ Selecteer school, vul Microsoft e-mail in, kies rol
```

### Stap 5: Leerkrachten toevoegen (school ICT of directeur)
```
Directeur dashboard → Leerkracht toevoegen
```

---

## Automatische schoolkoppeling via e-maildomein

Als je een e-maildomein koppelt aan een school (bv. `dekrekel.be`),
dan wordt elke nieuwe gebruiker die inlogt met een adres op dat domein
**automatisch** aan die school gekoppeld met de rol `teacher`.

Handig als leerkrachten zelf de URL krijgen en inloggen zonder dat je
ze eerst handmatig hoeft toe te voegen.

---

## Onderhoud

### Database backup
```bash
docker compose exec db pg_dump -U leerdoelen leerdoelen > backup_$(date +%Y%m%d).sql
```

### Doelen updaten
```bash
# Nieuwe JSON bestanden kopiëren
cp -r doelen/ /pad/naar/leerdoelen/doelen/
docker compose restart backend
```

### Logs
```bash
docker compose logs -f backend
```

---

## CI/CD via Gitea Actions

### Hoe het werkt

Bij elke push op `main`:
1. Runner bouwt de Docker image van `./backend`
2. Image wordt gepusht naar de Gitea Container Registry met twee tags:
   - `:latest` — altijd de meest recente versie
   - `:sha-<commithash>` — voor traceerbaarheid en rollback
3. Runner SSH't naar de VPS → `docker compose pull && docker compose up -d`

### Eenmalige setup in Gitea

#### 1. Repository variabelen (Settings → Actions → Variables)

| Naam | Waarde | Uitleg |
|---|---|---|
| `GITEA_REGISTRY` | `gitea.jouwdomein.be` | Hostname van je Gitea instantie |

#### 2. Repository secrets (Settings → Actions → Secrets)

| Naam | Waarde | Uitleg |
|---|---|---|
| `REGISTRY_USER` | `jouw-gitea-gebruikersnaam` | Gitea login voor de registry |
| `REGISTRY_TOKEN` | `gitea_xxxx...` | Gitea Access Token (Settings → Applications → Generate token, scope: `package:write`) |
| `DEPLOY_HOST` | `123.456.789.0` | IP of hostnaam van de app-VPS |
| `DEPLOY_USER` | `deploy` | SSH gebruiker op de VPS |
| `DEPLOY_SSH_KEY` | `-----BEGIN OPENSSH...` | Privésleutel (zie stap 3) |
| `DEPLOY_PORT` | `22` | SSH poort (weglaten = standaard 22) |
| `DEPLOY_PATH` | `/opt/leerdoelen` | Pad naar de docker-compose map op de VPS |

#### 3. SSH deploy key aanmaken

Voer dit uit op je **lokale machine** (niet op de VPS):

```bash
ssh-keygen -t ed25519 -C "gitea-deploy" -f ~/.ssh/gitea_deploy -N ""
```

Publieke sleutel toevoegen aan de VPS:
```bash
cat ~/.ssh/gitea_deploy.pub | ssh user@jouw-vps "cat >> ~/.ssh/authorized_keys"
```

Privésleutel kopiëren naar Gitea secret `DEPLOY_SSH_KEY`:
```bash
cat ~/.ssh/gitea_deploy
```

#### 4. `.env` op de VPS aanpassen

Voeg toe aan `/opt/leerdoelen/.env`:
```
BACKEND_IMAGE=gitea.jouwdomein.be/jouw-org/leerdoelen-tracker:latest
```

#### 5. Eerste push

```bash
git init
git remote add origin https://gitea.jouwdomein.be/jouw-org/leerdoelen-tracker.git
git add .
git commit -m "Initial commit"
git push -u origin main
```

De pipeline start automatisch. Je kan de voortgang volgen via
**Gitea → jouw repo → Actions**.

### Handmatig deployen

Via de Gitea UI: **Actions → Build, Push & Deploy → Run workflow**

Of via de VPS zelf (zonder pipeline):
```bash
cd /opt/leerdoelen
docker compose pull backend
docker compose up -d --no-deps backend
```

### Rollback naar vorige versie

```bash
# Bekijk beschikbare tags in de registry
# Pas de image tag aan in .env:
BACKEND_IMAGE=gitea.jouwdomein.be/jouw-org/leerdoelen-tracker:sha-a1b2c3d4

docker compose pull backend
docker compose up -d --no-deps backend
```
