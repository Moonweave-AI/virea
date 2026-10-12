"""Resumable, verified downloads with byte counts shared by every setup client."""

from __future__ import annotations

import asyncio
import hashlib
import time


def checksum(path, algorithm, git_blob=False):
    digest = hashlib.new(algorithm)
    if git_blob:
        digest.update(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


async def download(
    jobs,
    identifier,
    client,
    *,
    url,
    path,
    size,
    digest,
    algorithm="sha256",
    git_blob=False,
    completed=0,
    total=0,
):
    path.parent.mkdir(parents=True, exist_ok=True)
    if (
        path.is_file()
        and path.stat().st_size == size
        and await asyncio.to_thread(checksum, path, algorithm, git_blob) == digest
    ):
        jobs.update(
            identifier,
            downloaded_bytes=completed + size,
            total_bytes=total,
            file=path.name,
        )
        return
    partial = path.with_name(path.name + ".download")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > size:
        offset = 0
    jobs.output(identifier, f"Downloading {path.name}")
    async with client.stream(
        "GET", url, headers={"Range": f"bytes={offset}-"} if offset else {}, timeout=90
    ) as response:
        if response.status_code == 416 and offset == size:
            pass
        else:
            response.raise_for_status()
            if response.status_code != 206:
                offset = 0
            elif not response.headers.get("content-range", "").startswith(
                f"bytes {offset}-"
            ):
                raise ValueError("Download server returned an inconsistent byte range")
            last = 0
            with partial.open("ab" if offset else "wb") as output:
                async for block in response.aiter_bytes(256 * 1024):
                    output.write(block)
                    offset += len(block)
                    now = time.monotonic()
                    if now - last >= 0.4 or offset >= size:
                        jobs.update(
                            identifier,
                            downloaded_bytes=completed + offset,
                            total_bytes=total,
                            stage_percent=round((completed + offset) / total * 100, 1)
                            if total
                            else None,
                            file=path.name,
                            last_output_at=time.time(),
                        )
                        last = now
    if (
        partial.stat().st_size != size
        or await asyncio.to_thread(checksum, partial, algorithm, git_blob) != digest
    ):
        partial.unlink(missing_ok=True)
        raise ValueError(f"文件校验失败：{path.name}；重试会重新下载此文件")
    partial.replace(path)


async def huggingface_snapshot(jobs, identifier, client, repository, revision, root):
    metadata = await client.get(
        f"https://huggingface.co/api/models/{repository}/revision/{revision}",
        params={"blobs": "true"},
    )
    metadata.raise_for_status()
    rows = [
        r
        for r in metadata.json()["siblings"]
        if not r["rfilename"].startswith(".")
        and not r["rfilename"].endswith((".jpg", ".jpeg", ".png"))
    ]
    total = sum(r["size"] for r in rows)
    completed = 0
    for index, row in enumerate(rows):
        path = (root / row["rfilename"]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Unexpected model file path")
        lfs = row.get("lfs", {})
        jobs.update(identifier, files_done=index, files_total=len(rows))
        await download(
            jobs,
            identifier,
            client,
            url=f"https://huggingface.co/{repository}/resolve/{revision}/{row['rfilename']}",
            path=path,
            size=row["size"],
            digest=lfs.get("sha256") or row["blobId"],
            algorithm="sha256" if lfs else "sha1",
            git_blob=not lfs,
            completed=completed,
            total=total,
        )
        completed += row["size"]
    jobs.update(
        identifier,
        files_done=len(rows),
        stage_percent=100,
        downloaded_bytes=total,
        total_bytes=total,
    )
