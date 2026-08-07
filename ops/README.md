# Operational assets

These files are reference assets for deploying and operating applications that use
ProdKit Storage. They are intentionally separate from the Python runtime package.

- `backup/verify_postgres_backup.py` — logical backup/restore verification.
- `load/storage_smoke.py` — concurrent PostgreSQL/Redis saturation smoke.
- `failure/dependency_failure_smoke.py` — bounded unavailable-dependency failure smoke.
- `prometheus/prodkit-storage-alerts.yml` — starter Prometheus alert rules.
- `grafana/prodkit-storage-dashboard.json` — starter Grafana dashboard.
- `terraform/README.md` — provider-neutral infrastructure contract.

Related incident procedures live under `docs/runbooks/`.

These are **starting points**, not proof of production readiness. Provider-specific HA,
PITR, networking, encryption, secret management, capacity, RPO/RTO, and alert-routing
configuration must be validated in each deployment.
