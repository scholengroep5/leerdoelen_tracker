"""
Gunicorn configuratie voor de Leerdoelen Tracker.

Belasting voor deze app:
  ~264 gebruikers totaal (12 scholen × ~22 per school)
  Piekgebruik: 50-80 gelijktijdig tijdens studiedagen
  ~2-3 requests/seconde op piekmomenten

Worker formule: (2 × CPU-cores) + 1
  Voor een typische VPS met 2 vCPU: 5 workers
  Elke worker kan 1 request tegelijk afhandelen (sync worker).
  Met 4 workers + 2 threads = effectief 8 gelijktijdige requests —
  ruim voldoende voor deze schaal.
"""

import multiprocessing
import os

# ── Workers ───────────────────────────────────────────────────────────────────
# Instelbaar via env voor flexibiliteit op grotere of kleinere servers
workers     = int(os.environ.get('GUNICORN_WORKERS', multiprocessing.cpu_count() * 2 + 1))
threads     = int(os.environ.get('GUNICORN_THREADS', 2))
worker_class = 'gthread'   # threads-based: beter voor I/O-bound Flask apps

# ── Binding ───────────────────────────────────────────────────────────────────
bind        = '0.0.0.0:5000'

# ── Timeouts ──────────────────────────────────────────────────────────────────
timeout          = 60    # worker killed na 60s — voorkomt hangende processen
graceful_timeout = 30    # tijd om lopende requests af te werken bij restart
keepalive        = 5     # HTTP keep-alive seconden (nginx hergebruikt connecties)

# ── Logging ───────────────────────────────────────────────────────────────────
accesslog   = '-'        # stdout → docker logs
errorlog    = '-'        # stderr → docker logs
loglevel    = os.environ.get('LOG_LEVEL', 'info')
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s %(D)sµs'

# ── Worker lifecycle ──────────────────────────────────────────────────────────
# Herstart workers na N requests — voorkomt memory leaks over tijd
max_requests          = 1000
max_requests_jitter   = 100   # willekeurige offset voorkomt gelijktijdige restarts

# ── Process naam ──────────────────────────────────────────────────────────────
proc_name = 'leerdoelen-tracker'
