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
# Ga naar https://leerdoelen.sgr5.be/auth/setup
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
http://leerdoelen.scholengroep.be/auth/setup
→ Stel wachtwoord in voor admin@leerdoelen.local (is een vaste waarde)
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
# Nieuwe JSON bestanden kopiëren | kan ook in de WebUI door scholengroep ICT
cp -r doelen/ /pad/naar/leerdoelen/doelen/
docker compose restart backend
```

### Logs
```bash
docker compose logs -f backend
```

---

## CI/CD via Github Actions

### Hoe het werkt

Bij elke push op `main`:
1. Runner bouwt de Docker image van `./backend`
2. Image wordt gepusht naar de Github Container Registry met twee tags:
   - `:latest` — altijd de meest recente versie
   - `:sha-<commithash>` — voor traceerbaarheid en rollback

Bij elke tag met `v*` om met versies en releases te werken
   - `:vx.x.x` — pinnen op stabiele versies

### Rollback naar vorige versie

```bash
# Bekijk beschikbare tags in de registry
# Pas de image tag aan in .env:
BACKEND_IMAGE=ghcr.io/jouw-org/leerdoelen-tracker:sha-a1b2c3d4

docker compose pull backend
docker compose up -d --no-deps backend
```

---

## ⚖️ Licentie

Copyright © 2025-2026 GO! Scholengroep 5. Alle rechten voorbehouden.

Deze software is eigendom van GO! Scholengroep 5 en is uitsluitend bestemd voor intern gebruik binnen de scholengroep en de aangesloten scholen. Verspreiding, publicatie of gebruik buiten de organisatie is niet toegestaan zonder schriftelijke toestemming.

Zie het [LICENSE](./LICENSE) bestand voor de volledige licentietekst.