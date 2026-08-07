FROM python:3.13-slim@sha256:bf503bb2243c5aad0aa951544dd60d165f992646441d35dea90893703fc26251 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && python -m pip uninstall --yes setuptools msgpack \
    && python -m pip check \
    && python - <<'PY'
from importlib.metadata import PackageNotFoundError, distribution

for package in ("msgpack", "setuptools"):
    try:
        installed = distribution(package)
    except PackageNotFoundError:
        continue
    raise SystemExit(
        f"unexpected runtime distribution {package}=={installed.version}; "
        "remove the Trivy exception only after updating the base-image SBOM"
    )
PY
USER app
ENTRYPOINT ["prodkit-storage"]
CMD ["doctor"]
