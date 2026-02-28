# Security beleid

## Kwetsbaarheden melden

Gevonden een beveiligingsprobleem? Stuur een e-mail naar de systeembeheerder van jouw scholengroep.  
Voeg zo veel mogelijk detail toe: stappen om te reproduceren, impact, en eventueel een proof-of-concept.

Publiceer kwetsbaarheden **niet** publiek voordat ze zijn opgelost.

---

## Beveiligingsmaatregelen in deze applicatie

### Authenticatie
- Primaire login via Microsoft Entra ID (Azure AD) — geen wachtwoorden opgeslagen voor gewone gebruikers
- Superadmin wachtwoord gehasht met **scrypt** (sterk geheugenintensief algoritme)
- OAuth2 state parameter validatie — beschermt tegen CSRF in OAuth flow
- `?next=` redirect parameter gevalideerd — beschermt tegen open redirect aanvallen
- Session cookies: `HttpOnly`, `Secure` (HTTPS), `SameSite=Lax`

### Rate limiting
| Endpoint | Limiet |
|----------|--------|
| Alle `/auth/*` routes | 10 per minuut per IP |
| Superadmin login | 10/min + 30/uur per IP |
| API endpoints | 120 per minuut per IP |
| Doelen upload | 5 per minuut per IP |
| Setup endpoint | 5 per minuut per IP |

Rate limiting via **Redis** (persistent over meerdere workers).  
Nginx voegt een extra laag rate limiting toe vóór Flask.

### HTTP Security headers
Via Flask-Talisman + Nginx:
- `Content-Security-Policy` — nonce-based, geen unsafe-inline scripts
- `Strict-Transport-Security` — HSTS 1 jaar, incl. subdomains
- `X-Frame-Options: DENY` — clickjacking preventie
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy` — geen toegang tot camera/microfoon/locatie
- `form-action: 'self'` — voorkomt form hijacking
- `base-uri: 'self'` — voorkomt base tag injection
- `object-src: 'none'` — geen Flash of plugins

### Autorisatie
- Rolgebaseerde toegangscontrole (superadmin → scholengroep_ict → school_ict → director → teacher)
- Elke API route heeft expliciete rolauthenticatie decorator
- School-isolatie: gebruikers kunnen enkel data van hun eigen school zien
- Auditlog van alle beheerhandelingen

### Database
- Parameterized queries via SQLAlchemy ORM — geen raw SQL met gebruikersinput
- Non-root database gebruiker
- PostgreSQL container niet publiek blootgesteld (intern Docker netwerk)

### Infrastructuur
- Flask draait als non-root gebruiker (`appuser`) in Docker container
- Read-only volume mount voor doelen JSON bestanden
- Redis beveiligd met wachtwoord
- Backend enkel bereikbaar via `127.0.0.1` (niet publiek)
- Nginx als reverse proxy met request size limiting en timeouts (Slowloris bescherming)

---

## Dependency updates

Controleer regelmatig op kwetsbaarheden in dependencies:

```bash
pip install pip-audit
pip-audit -r backend/requirements.txt
```

Python base image: pin op specifieke patch versie in `Dockerfile`.  
Controleer updates op: https://hub.docker.com/_/python

---

## Checklist voor nieuwe deployment

- [ ] `SECRET_KEY` gegenereerd met `python3 -c "import secrets; print(secrets.token_hex(32))"`
- [ ] `POSTGRES_PASSWORD` sterk en uniek
- [ ] `REDIS_PASSWORD` ingesteld
- [ ] `BASE_URL` correct ingesteld op HTTPS URL
- [ ] SSL/TLS certificaat aanwezig (Let's Encrypt via Certbot)
- [ ] Microsoft Entra ID app registratie correct geconfigureerd
- [ ] Superadmin wachtwoord ingesteld via `/auth/setup` (min. 12 tekens)
- [ ] `/auth/setup` endpoint niet meer toegankelijk na setup (wordt automatisch geblokkeerd)
- [ ] Firewall: enkel poorten 80 en 443 publiek open
