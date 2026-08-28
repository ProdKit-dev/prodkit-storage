FROM python:3.14-slim@sha256:cae66f2ef0ec51a9891263eeee7f987dacf0a9879e8aa9353d5606e0530619a5 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get upgrade --yes \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app
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
