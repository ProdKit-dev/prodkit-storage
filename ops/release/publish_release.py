from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

TRANSIENT_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
CHECKSUM_RE = re.compile(r"^(?P<digest>[0-9a-f]{64})  (?P<name>[^/].*)$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class ReleaseError(RuntimeError):
    """Fail-closed release publication error."""


class ApiError(ReleaseError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"GitHub API returned HTTP {status}: {message}")
        self.status = status


@dataclass(frozen=True, slots=True)
class LocalAsset:
    name: str
    path: Path
    size: int
    digest: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_local_assets(dist: Path, *, tag: str) -> dict[str, LocalAsset]:
    if not dist.is_dir():
        raise ReleaseError(f"release directory does not exist: {dist}")
    files = sorted(path for path in dist.iterdir() if path.is_file())
    if not files:
        raise ReleaseError("release directory contains no files")

    hidden = sorted(path.name for path in files if path.name.startswith("."))
    if hidden:
        raise ReleaseError(f"release directory contains hidden files: {hidden}")

    by_name = {path.name: path for path in files}
    checksum_path = by_name.get("SHA256SUMS")
    if checksum_path is None:
        raise ReleaseError("release directory is missing SHA256SUMS")

    payload_names = set(by_name) - {"SHA256SUMS"}
    source_name = f"prodkit-storage-{tag}-source.tar.gz"
    wheel_names = sorted(name for name in payload_names if name.endswith(".whl"))
    sdist_names = sorted(
        name
        for name in payload_names
        if name.endswith(".tar.gz") and name != source_name
    )
    if (
        len(payload_names) != 3
        or len(wheel_names) != 1
        or len(sdist_names) != 1
        or source_name not in payload_names
    ):
        raise ReleaseError(
            "release payload must contain exactly one wheel, one sdist, and "
            f"{source_name}; found={sorted(payload_names)}"
        )

    manifest: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        checksum_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        match = CHECKSUM_RE.fullmatch(raw_line)
        if match is None:
            raise ReleaseError(f"invalid SHA256SUMS line {line_number}")
        name = match.group("name")
        if name in manifest:
            raise ReleaseError(f"duplicate SHA256SUMS entry: {name}")
        manifest[name] = match.group("digest")

    if set(manifest) != payload_names:
        missing = sorted(payload_names - set(manifest))
        extra = sorted(set(manifest) - payload_names)
        raise ReleaseError(f"SHA256SUMS asset set mismatch; missing={missing}, extra={extra}")

    assets: dict[str, LocalAsset] = {}
    for name, path in by_name.items():
        digest = sha256_file(path)
        if name != "SHA256SUMS" and manifest[name] != digest:
            raise ReleaseError(f"local checksum mismatch: {name}")
        assets[name] = LocalAsset(name=name, path=path, size=path.stat().st_size, digest=digest)
    return assets


def remote_digest(asset: dict[str, Any]) -> str | None:
    value = asset.get("digest")
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return None
    return value.removeprefix("sha256:")


def asset_matches(local: LocalAsset, remote: dict[str, Any]) -> bool:
    return (
        remote.get("name") == local.name
        and remote.get("size") == local.size
        and remote_digest(remote) == local.digest
    )


def verify_remote_assets(
    expected: dict[str, LocalAsset],
    remote_assets: list[dict[str, Any]],
) -> None:
    by_name: dict[str, list[dict[str, Any]]] = {}
    for remote in remote_assets:
        name = remote.get("name")
        if not isinstance(name, str):
            raise ReleaseError("GitHub returned an asset without a name")
        by_name.setdefault(name, []).append(remote)

    if set(by_name) != set(expected):
        missing = sorted(set(expected) - set(by_name))
        extra = sorted(set(by_name) - set(expected))
        raise ReleaseError(f"remote release asset set mismatch; missing={missing}, extra={extra}")

    for name, local in expected.items():
        matches = by_name[name]
        if len(matches) != 1:
            raise ReleaseError(f"remote release contains duplicate asset: {name}")
        if not asset_matches(local, matches[0]):
            raise ReleaseError(f"remote release asset digest/size mismatch: {name}")


class GitHubClient:
    def __init__(self, *, token: str, api_url: str, max_attempts: int = 8) -> None:
        if not token:
            raise ReleaseError("GITHUB_TOKEN is required")
        if max_attempts < 1 or max_attempts > 20:
            raise ReleaseError("RELEASE_MAX_ATTEMPTS must be between 1 and 20")
        parsed = urlparse(api_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ReleaseError("GITHUB_API_URL must be an absolute HTTPS URL")
        self.token = token
        self.api_url = api_url.rstrip("/")
        self.max_attempts = max_attempts

    def headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "prodkit-storage-release-publisher",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if extra:
            headers.update(extra)
        return headers

    @staticmethod
    def error_message(error: HTTPError) -> str:
        try:
            body = error.read().decode("utf-8", errors="replace")
            payload = json.loads(body)
            if isinstance(payload, dict) and isinstance(payload.get("message"), str):
                return str(payload["message"])
            return body[:500]
        except (OSError, UnicodeError, json.JSONDecodeError):
            return str(error.reason)

    @staticmethod
    def backoff(attempt: int, retry_after: str | None = None) -> None:
        delay = min(30.0, float(2 ** (attempt - 1)))
        if retry_after and retry_after.isdigit():
            delay = min(60.0, max(delay, float(retry_after)))
        time.sleep(delay)

    def request(
        self,
        method: str,
        url: str,
        *,
        data: bytes | None = None,
        content_type: str | None = None,
        expected: frozenset[int] = frozenset({200}),
        retry: bool = True,
    ) -> Any:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ReleaseError("refusing non-HTTPS GitHub API request")
        extra = {"Content-Type": content_type} if content_type else None
        attempts = self.max_attempts if retry else 1
        for attempt in range(1, attempts + 1):
            request = Request(  # noqa: S310 - URL is validated as absolute HTTPS above.
                url=url,
                data=data,
                headers=self.headers(extra),
                method=method,
            )
            try:
                with urlopen(request, timeout=60) as response:  # noqa: S310
                    status = int(response.status)
                    body = response.read()
                    if status not in expected:
                        raise ApiError(status, "unexpected success response")
                    if not body:
                        return None
                    return json.loads(body.decode("utf-8"))
            except HTTPError as error:
                status = int(error.code)
                message = self.error_message(error)
                if retry and status in TRANSIENT_STATUSES and attempt < attempts:
                    self.backoff(attempt, error.headers.get("Retry-After"))
                    continue
                raise ApiError(status, message) from error
            except URLError as error:
                if retry and attempt < attempts:
                    self.backoff(attempt)
                    continue
                raise ReleaseError(f"GitHub API network error: {error.reason}") from error
            except json.JSONDecodeError as error:
                raise ReleaseError("GitHub API returned invalid JSON") from error
        raise ReleaseError("GitHub API retry loop exhausted")

    def json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        expected: frozenset[int] = frozenset({200}),
        retry: bool = True,
    ) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        return self.request(
            method,
            f"{self.api_url}{path}",
            data=data,
            content_type="application/json" if data is not None else None,
            expected=expected,
            retry=retry,
        )

    def list_releases(self, repository: str) -> list[dict[str, Any]]:
        releases: list[dict[str, Any]] = []
        for page in range(1, 101):
            payload = self.json(
                "GET",
                f"/repos/{repository}/releases?per_page=100&page={page}",
            )
            if not isinstance(payload, list):
                raise ReleaseError("GitHub returned invalid release list")
            releases.extend(item for item in payload if isinstance(item, dict))
            if len(payload) < 100:
                return releases
        raise ReleaseError("release pagination exceeded safety bound")

    def find_release(self, repository: str, tag: str) -> dict[str, Any] | None:
        matches = [item for item in self.list_releases(repository) if item.get("tag_name") == tag]
        if len(matches) > 1:
            raise ReleaseError(f"multiple GitHub releases found for tag {tag}")
        return matches[0] if matches else None

    def create_draft(self, repository: str, tag: str, target_sha: str) -> dict[str, Any]:
        payload = self.json(
            "POST",
            f"/repos/{repository}/releases",
            payload={
                "tag_name": tag,
                "target_commitish": target_sha,
                "name": tag,
                "draft": True,
                "prerelease": False,
                "generate_release_notes": True,
            },
            expected=frozenset({201}),
        )
        if not isinstance(payload, dict):
            raise ReleaseError("GitHub returned invalid created release")
        return payload

    def update_release(
        self,
        repository: str,
        release_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        result = self.json(
            "PATCH",
            f"/repos/{repository}/releases/{release_id}",
            payload=payload,
        )
        if not isinstance(result, dict):
            raise ReleaseError("GitHub returned invalid updated release")
        return result

    def list_assets(self, repository: str, release_id: int) -> list[dict[str, Any]]:
        assets: list[dict[str, Any]] = []
        for page in range(1, 101):
            payload = self.json(
                "GET",
                f"/repos/{repository}/releases/{release_id}/assets?per_page=100&page={page}",
            )
            if not isinstance(payload, list):
                raise ReleaseError("GitHub returned invalid release asset list")
            assets.extend(item for item in payload if isinstance(item, dict))
            if len(payload) < 100:
                return assets
        raise ReleaseError("release asset pagination exceeded safety bound")

    def delete_asset(self, repository: str, asset_id: int) -> None:
        self.json(
            "DELETE",
            f"/repos/{repository}/releases/assets/{asset_id}",
            expected=frozenset({204}),
        )

    def upload_asset(self, release: dict[str, Any], local: LocalAsset) -> dict[str, Any]:
        upload_url = release.get("upload_url")
        if not isinstance(upload_url, str):
            raise ReleaseError("release metadata is missing upload_url")
        base_url = upload_url.split("{", 1)[0]
        url = f"{base_url}?{urlencode({'name': local.name})}"
        content_type = mimetypes.guess_type(local.name)[0] or "application/octet-stream"
        payload = self.request(
            "POST",
            url,
            data=local.path.read_bytes(),
            content_type=content_type,
            expected=frozenset({201}),
        )
        if not isinstance(payload, dict):
            raise ReleaseError(f"GitHub returned invalid uploaded asset: {local.name}")
        if not asset_matches(local, payload):
            raise ReleaseError(f"uploaded asset digest/size mismatch: {local.name}")
        return payload

    def tag_target(self, repository: str, tag: str) -> str | None:
        encoded = quote(tag, safe="")
        try:
            ref = self.json("GET", f"/repos/{repository}/git/ref/tags/{encoded}")
        except ApiError as error:
            if error.status == 404:
                return None
            raise
        if not isinstance(ref, dict):
            raise ReleaseError("GitHub returned invalid tag reference")
        obj = ref.get("object")
        for _ in range(8):
            if not isinstance(obj, dict):
                raise ReleaseError("Git tag reference is missing object metadata")
            obj_type = obj.get("type")
            sha = obj.get("sha")
            if not isinstance(sha, str):
                raise ReleaseError("Git tag reference is missing SHA")
            if obj_type == "commit":
                return sha
            if obj_type != "tag":
                raise ReleaseError(f"unsupported Git tag object type: {obj_type}")
            tag_object = self.json("GET", f"/repos/{repository}/git/tags/{sha}")
            if not isinstance(tag_object, dict):
                raise ReleaseError("GitHub returned invalid annotated tag")
            obj = tag_object.get("object")
        raise ReleaseError("tag indirection exceeded safety bound")


def release_id(release: dict[str, Any]) -> int:
    value = release.get("id")
    if not isinstance(value, int):
        raise ReleaseError("release metadata is missing numeric id")
    return value


def verify_release_metadata(release: dict[str, Any], *, target_sha: str) -> None:
    if release.get("draft") is not False:
        raise ReleaseError("release is still draft")
    if release.get("prerelease") is not False:
        raise ReleaseError("release unexpectedly marked prerelease")
    if release.get("target_commitish") != target_sha:
        raise ReleaseError("release target_commitish does not match exact release SHA")


def prepare_draft_release(
    client: GitHubClient,
    repository: str,
    release: dict[str, Any],
    *,
    target_sha: str,
) -> dict[str, Any]:
    """Return a draft pinned to the exact release SHA.

    A previous failed promotion may leave a draft release behind before GitHub
    creates the tag. Retargeting is allowed only while the release is still a
    draft; callers must verify any existing tag before invoking this helper.
    Published releases remain immutable and are handled separately.
    """

    if release.get("draft") is not True:
        raise ReleaseError("existing release is neither draft nor published")

    if release.get("target_commitish") != target_sha or release.get("prerelease") is not False:
        release = client.update_release(
            repository,
            release_id(release),
            {
                "draft": True,
                "prerelease": False,
                "target_commitish": target_sha,
            },
        )

    if release.get("draft") is not True:
        raise ReleaseError("prepared release unexpectedly stopped being a draft")
    if release.get("prerelease") is not False:
        raise ReleaseError("prepared draft unexpectedly marked prerelease")
    if release.get("target_commitish") != target_sha:
        raise ReleaseError("prepared draft does not target exact release SHA")
    return release


def sync_draft_assets(
    client: GitHubClient,
    repository: str,
    release: dict[str, Any],
    expected: dict[str, LocalAsset],
) -> None:
    rid = release_id(release)
    remote = client.list_assets(repository, rid)
    by_name: dict[str, list[dict[str, Any]]] = {}
    for item in remote:
        name = item.get("name")
        if isinstance(name, str):
            by_name.setdefault(name, []).append(item)

    for name, local in expected.items():
        matches = by_name.get(name, [])
        if len(matches) == 1 and asset_matches(local, matches[0]):
            continue
        for item in matches:
            asset_id = item.get("id")
            if not isinstance(asset_id, int):
                raise ReleaseError(f"remote asset lacks numeric id: {name}")
            client.delete_asset(repository, asset_id)
        client.upload_asset(release, local)

    remote = client.list_assets(repository, rid)
    extras = [item for item in remote if item.get("name") not in expected]
    for item in extras:
        asset_id = item.get("id")
        if not isinstance(asset_id, int):
            raise ReleaseError("unexpected remote asset lacks numeric id")
        client.delete_asset(repository, asset_id)
    verify_remote_assets(expected, client.list_assets(repository, rid))


def publish(dist: Path) -> None:
    token = os.environ.get("GITHUB_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    target_sha = os.environ.get("GITHUB_SHA", "")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    tag = os.environ.get("RELEASE_TAG", "")
    max_attempts = int(os.environ.get("RELEASE_MAX_ATTEMPTS", "8"))

    if repository.count("/") != 1:
        raise ReleaseError("GITHUB_REPOSITORY must be owner/name")
    if SHA_RE.fullmatch(target_sha) is None:
        raise ReleaseError("GITHUB_SHA must be a lowercase 40-character SHA")
    if not tag.startswith("v") or len(tag) < 2:
        raise ReleaseError("RELEASE_TAG must start with v")

    expected = load_local_assets(dist, tag=tag)
    client = GitHubClient(token=token, api_url=api_url, max_attempts=max_attempts)
    release = client.find_release(repository, tag)

    if release is not None and release.get("draft") is False:
        verify_release_metadata(release, target_sha=target_sha)
        if client.tag_target(repository, tag) != target_sha:
            raise ReleaseError("published tag does not resolve to exact release SHA")
        verify_remote_assets(expected, client.list_assets(repository, release_id(release)))
        print(f"release {tag} is already published and verified")
        return

    existing_tag = client.tag_target(repository, tag)
    if existing_tag is not None and existing_tag != target_sha:
        raise ReleaseError(f"existing tag {tag} resolves to unexpected SHA {existing_tag}")

    if release is None:
        release = client.create_draft(repository, tag, target_sha)
    else:
        release = prepare_draft_release(
            client,
            repository,
            release,
            target_sha=target_sha,
        )

    sync_draft_assets(client, repository, release, expected)
    rid = release_id(release)
    published = client.update_release(
        repository,
        rid,
        {"draft": False, "prerelease": False, "target_commitish": target_sha},
    )
    verify_release_metadata(published, target_sha=target_sha)
    if client.tag_target(repository, tag) != target_sha:
        raise ReleaseError("published tag does not resolve to exact release SHA")
    verify_remote_assets(expected, client.list_assets(repository, rid))
    print(f"published and verified {tag} at {target_sha} with {len(expected)} assets")


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        print("usage: publish_release.py DIST_DIRECTORY", file=sys.stderr)
        return 2
    try:
        publish(Path(arguments[0]))
    except (ReleaseError, OSError, ValueError) as error:
        print(f"release publication failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
