FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS runtime

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
    && python -m pip uninstall --yes pip \
    && python - <<'PY'
from importlib.metadata import PackageNotFoundError, distribution

for package in ("msgpack", "setuptools", "pip"):
    try:
        installed = distribution(package)
    except PackageNotFoundError:
        continue
    raise SystemExit(
        f"unexpected runtime distribution {package}=={installed.version}; "
        "remove the packaging-tools exception only after updating the image SBOM"
    )
PY
USER app
ENTRYPOINT ["prodkit-storage"]
CMD ["doctor"]
