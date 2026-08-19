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


class _RecoveryClient:
    def __init__(self, *, tag_target: str | None) -> None:
        self.current_tag_target = tag_target
        self.deleted: list[tuple[str, int]] = []
        self.created: list[tuple[str, str, str]] = []

    def tag_target(self, repository: str, tag: str) -> str | None:
        del repository, tag
        return self.current_tag_target

    def delete_release(self, repository: str, release_id: int) -> None:
        self.deleted.append((repository, release_id))

    def create_draft(
        self,
        repository: str,
        tag: str,
        target_sha: str,
    ) -> dict[str, Any]:
        self.created.append((repository, tag, target_sha))
        return {
            "id": 99,
            "tag_name": tag,
            "draft": True,
            "prerelease": False,
            "target_commitish": target_sha,
        }


class _TagClient:
    def __init__(self, *, initial: str | None) -> None:
        self.current = initial
        self.created: list[tuple[str, str, str]] = []

    def tag_target(self, repository: str, tag: str) -> str | None:
        del repository, tag
        return self.current

    def create_tag_ref(self, repository: str, tag: str, target_sha: str) -> None:
        self.created.append((repository, tag, target_sha))
        self.current = target_sha


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

    with pytest.raises(publisher.ReleaseError, match="not a draft"):
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


def test_prepare_release_rebuilds_published_release_without_git_tag() -> None:
    client = _RecoveryClient(tag_target=None)
    target = "d" * 40

    prepared, already_published = publisher.prepare_release_for_publication(
        client,
        "ProdKit-dev/prodkit-storage",
        {
            "id": 44,
            "tag_name": "v0.4.0",
            "draft": False,
            "prerelease": False,
            "target_commitish": "a" * 40,
        },
        tag="v0.4.0",
        target_sha=target,
    )

    assert already_published is False
    assert prepared == {
        "id": 99,
        "tag_name": "v0.4.0",
        "draft": True,
        "prerelease": False,
        "target_commitish": target,
    }
    assert client.deleted == [("ProdKit-dev/prodkit-storage", 44)]
    assert client.created == [("ProdKit-dev/prodkit-storage", "v0.4.0", target)]


def test_prepare_release_accepts_only_exact_published_tag() -> None:
    target = "e" * 40
    client = _RecoveryClient(tag_target=target)
    release = {
        "id": 45,
        "tag_name": "v0.4.0",
        "draft": False,
        "prerelease": False,
        "target_commitish": target,
    }

    prepared, already_published = publisher.prepare_release_for_publication(
        client,
        "ProdKit-dev/prodkit-storage",
        release,
        tag="v0.4.0",
        target_sha=target,
    )

    assert prepared is release
    assert already_published is True
    assert client.deleted == []
    assert client.created == []


def test_prepare_release_rejects_wrong_existing_tag() -> None:
    client = _RecoveryClient(tag_target="f" * 40)

    with pytest.raises(publisher.ReleaseError, match="unexpected SHA"):
        publisher.prepare_release_for_publication(
            client,
            "ProdKit-dev/prodkit-storage",
            None,
            tag="v0.4.0",
            target_sha="a" * 40,
        )

    assert client.deleted == []
    assert client.created == []


def test_ensure_exact_tag_creates_missing_tag_before_publication() -> None:
    client = _TagClient(initial=None)
    target = "1" * 40

    publisher.ensure_exact_tag(
        client,
        "ProdKit-dev/prodkit-storage",
        tag="v0.4.0",
        target_sha=target,
    )

    assert client.current == target
    assert client.created == [("ProdKit-dev/prodkit-storage", "v0.4.0", target)]


def test_ensure_exact_tag_leaves_exact_tag_untouched() -> None:
    target = "2" * 40
    client = _TagClient(initial=target)

    publisher.ensure_exact_tag(
        client,
        "ProdKit-dev/prodkit-storage",
        tag="v0.4.0",
        target_sha=target,
    )

    assert client.created == []


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
