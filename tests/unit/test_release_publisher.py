from __future__ import annotations

import importlib.util
import sys
from hashlib import sha256
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _load_publisher() -> ModuleType:
    path = Path(__file__).parents[2] / "ops" / "release" / "publish_release.py"
    spec = importlib.util.spec_from_file_location("prodkit_storage_release_publisher", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


publisher = _load_publisher()


class _DraftClient:
    def __init__(self) -> None:
        self.updates: list[tuple[str, int, dict[str, Any]]] = []

    def update_release(
        self,
        repository: str,
        release_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.updates.append((repository, release_id, payload))
        return {
            "id": release_id,
            "tag_name": "v0.4.0",
            "draft": payload["draft"],
            "prerelease": payload["prerelease"],
            "target_commitish": payload["target_commitish"],
        }


def _write_release_assets(directory: Path, *, tag: str = "v0.4.0") -> None:
    payloads = {
        "prodkit_storage-0.4.0-py3-none-any.whl": b"wheel",
        "prodkit_storage-0.4.0.tar.gz": b"sdist",
        f"prodkit-storage-{tag}-source.tar.gz": b"source",
    }
    lines: list[str] = []
    for name, content in payloads.items():
        path = directory / name
        path.write_bytes(content)
        lines.append(f"{sha256(content).hexdigest()}  {name}\n")
    (directory / "SHA256SUMS").write_text("".join(sorted(lines)), encoding="utf-8")


def test_prepare_draft_release_retargets_stale_unpublished_draft() -> None:
    client = _DraftClient()
    target = "b" * 40
    prepared = publisher.prepare_draft_release(
        client,
        "ProdKit-dev/prodkit-storage",
        {
            "id": 41,
            "tag_name": "v0.4.0",
            "draft": True,
            "prerelease": False,
            "target_commitish": "a" * 40,
        },
        target_sha=target,
    )

    assert prepared["draft"] is True
    assert prepared["prerelease"] is False
    assert prepared["target_commitish"] == target
    assert client.updates == [
        (
            "ProdKit-dev/prodkit-storage",
            41,
            {"draft": True, "prerelease": False, "target_commitish": target},
        )
    ]


def test_prepare_draft_release_never_mutates_published_release() -> None:
    client = _DraftClient()

    with pytest.raises(publisher.ReleaseError, match="neither draft nor published"):
        publisher.prepare_draft_release(
            client,
            "ProdKit-dev/prodkit-storage",
            {
                "id": 42,
                "draft": False,
                "prerelease": False,
                "target_commitish": "a" * 40,
            },
            target_sha="b" * 40,
        )

    assert client.updates == []


def test_prepare_draft_release_leaves_matching_draft_untouched() -> None:
    client = _DraftClient()
    target = "c" * 40
    release = {
        "id": 43,
        "draft": True,
        "prerelease": False,
        "target_commitish": target,
    }

    assert (
        publisher.prepare_draft_release(
            client,
            "ProdKit-dev/prodkit-storage",
            release,
            target_sha=target,
        )
        is release
    )
    assert client.updates == []


def test_load_local_assets_requires_exact_release_payload_shape(tmp_path: Path) -> None:
    _write_release_assets(tmp_path)

    assets = publisher.load_local_assets(tmp_path, tag="v0.4.0")

    assert set(assets) == {
        "SHA256SUMS",
        "prodkit_storage-0.4.0-py3-none-any.whl",
        "prodkit_storage-0.4.0.tar.gz",
        "prodkit-storage-v0.4.0-source.tar.gz",
    }


def test_load_local_assets_rejects_hidden_build_state(tmp_path: Path) -> None:
    _write_release_assets(tmp_path)
    (tmp_path / ".gitignore").write_text("*\n", encoding="utf-8")

    with pytest.raises(publisher.ReleaseError, match="hidden files"):
        publisher.load_local_assets(tmp_path, tag="v0.4.0")


def test_load_local_assets_rejects_extra_payload(tmp_path: Path) -> None:
    _write_release_assets(tmp_path)
    extra = tmp_path / "unexpected.txt"
    extra.write_text("unexpected", encoding="utf-8")
    checksum_file = tmp_path / "SHA256SUMS"
    checksum_file.write_text(
        checksum_file.read_text(encoding="utf-8")
        + f"{sha256(extra.read_bytes()).hexdigest()}  {extra.name}\n",
        encoding="utf-8",
    )

    with pytest.raises(publisher.ReleaseError, match="exactly one wheel"):
        publisher.load_local_assets(tmp_path, tag="v0.4.0")
