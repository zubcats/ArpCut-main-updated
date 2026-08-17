#!/usr/bin/env python3
"""Publish a rolling GitHub Release via ``gh``, retrying transient API errors.

Used by the Windows installer workflow so a GitHub blip does not fail a
finished PyInstaller/Inno build. Re-running only this job is cheap.

The public asset is the installer EXE only. Build metadata goes in the
release notes so users are not asked to extract two files.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ATTEMPTS = 8
DEFAULT_INITIAL_SLEEP_S = 10.0
DEFAULT_MAX_SLEEP_S = 45.0

GhRunner = Callable[[Sequence[str]], "GhResult"]


@dataclass(frozen=True)
class GhResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return f"{self.stdout}\n{self.stderr}"


class PublishError(RuntimeError):
    pass


def _default_runner(args: Sequence[str]) -> GhResult:
    proc = subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return GhResult(proc.returncode, proc.stdout or "", proc.stderr or "")


def _combined_lower(result: GhResult) -> str:
    return result.output.lower()


def is_not_found(result: GhResult) -> bool:
    text = _combined_lower(result)
    return "release not found" in text or "http 404" in text


def is_already_exists(result: GhResult) -> bool:
    text = _combined_lower(result)
    return "already exists" in text or "already_exists" in text


def resolve_file(path: Path) -> Path:
    if path.is_file():
        return path
    nested = Path("output") / path.name
    if nested.is_file():
        return nested
    flat = Path(path.name)
    if flat.is_file():
        return flat
    raise PublishError(f"Missing release file: {path}")


def _gh(runner: GhRunner, args: Sequence[str]) -> GhResult:
    return runner(["gh", *args])


def _require_ok(result: GhResult, action: str) -> None:
    if result.returncode == 0:
        if result.stdout.strip():
            print(result.stdout.rstrip())
        return
    detail = result.output.strip() or f"exit {result.returncode}"
    raise PublishError(f"{action} failed: {detail}")


def _notes_args(notes_file: Path | None) -> list[str]:
    if notes_file is not None:
        return ["--notes-file", str(notes_file)]
    return ["--notes", "Rolling installer."]


def _drop_stale_json_asset(runner: GhRunner, tag: str) -> None:
    """Older publishes attached build-info.json as a download; drop it."""
    _gh(runner, ["release", "delete-asset", tag, "build-info.json", "--yes"])


def _partition_files(
    files: Sequence[Path], notes_file: Path | None
) -> tuple[list[Path], Path | None]:
    keep: list[Path] = []
    notes = notes_file
    for path in files:
        if path.name.lower() == "build-info.json":
            notes = path
        else:
            keep.append(path)
    return keep, notes


def _edit_and_upload(
    runner: GhRunner,
    *,
    tag: str,
    title: str,
    target: str,
    prerelease: bool,
    files: Sequence[Path],
    notes_file: Path | None,
) -> None:
    edit_args = [
        "release",
        "edit",
        tag,
        "--title",
        title,
        "--target",
        target,
        "--latest=false",
        *_notes_args(notes_file),
    ]
    edit_args.append("--prerelease" if prerelease else "--prerelease=false")
    _require_ok(_gh(runner, edit_args), f"gh release edit {tag}")
    upload_args = ["release", "upload", tag, "--clobber", *[str(p) for p in files]]
    _require_ok(_gh(runner, upload_args), f"gh release upload {tag}")
    _drop_stale_json_asset(runner, tag)


def _create(
    runner: GhRunner,
    *,
    tag: str,
    title: str,
    target: str,
    prerelease: bool,
    files: Sequence[Path],
    notes_file: Path | None,
) -> GhResult:
    create_args = [
        "release",
        "create",
        tag,
        "--title",
        title,
        "--target",
        target,
        *_notes_args(notes_file),
        "--latest=false",
        *[str(p) for p in files],
    ]
    if prerelease:
        create_args.append("--prerelease")
    return _gh(runner, create_args)


def publish_once(
    runner: GhRunner,
    *,
    tag: str,
    title: str,
    target: str,
    prerelease: bool,
    files: Sequence[Path],
    notes_file: Path | None = None,
) -> None:
    files, notes_file = _partition_files(files, notes_file)
    if not files:
        raise PublishError("No installer file to publish")
    view = _gh(runner, ["release", "view", tag])
    if view.returncode == 0:
        _edit_and_upload(
            runner,
            tag=tag,
            title=title,
            target=target,
            prerelease=prerelease,
            files=files,
            notes_file=notes_file,
        )
        return
    if not is_not_found(view):
        raise PublishError(f"gh release view {tag} failed: {view.output.strip()}")

    created = _create(
        runner,
        tag=tag,
        title=title,
        target=target,
        prerelease=prerelease,
        files=files,
        notes_file=notes_file,
    )
    if created.returncode == 0:
        if created.stdout.strip():
            print(created.stdout.rstrip())
        _drop_stale_json_asset(runner, tag)
        return
    if is_already_exists(created):
        _edit_and_upload(
            runner,
            tag=tag,
            title=title,
            target=target,
            prerelease=prerelease,
            files=files,
            notes_file=notes_file,
        )
        return
    raise PublishError(f"gh release create {tag} failed: {created.output.strip()}")


def backoff_seconds(attempt: int, initial: float, maximum: float) -> float:
    return min(maximum, initial * (2 ** max(0, attempt - 1)))


def publish_with_retries(
    *,
    tag: str,
    title: str,
    target: str,
    prerelease: bool,
    files: Sequence[Path],
    notes_file: Path | None = None,
    attempts: int = DEFAULT_ATTEMPTS,
    initial_sleep_s: float = DEFAULT_INITIAL_SLEEP_S,
    max_sleep_s: float = DEFAULT_MAX_SLEEP_S,
    runner: GhRunner | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    resolved = [resolve_file(Path(p)) for p in files]
    notes_resolved = resolve_file(notes_file) if notes_file is not None else None
    use_runner = runner or _default_runner
    last_error = "unknown error"
    total = max(1, attempts)
    for attempt in range(1, total + 1):
        try:
            publish_once(
                use_runner,
                tag=tag,
                title=title,
                target=target,
                prerelease=prerelease,
                files=resolved,
                notes_file=notes_resolved,
            )
            print(f"Published {tag} on attempt {attempt}/{total}")
            return
        except PublishError as exc:
            last_error = str(exc)
            print(f"Publish attempt {attempt}/{total} failed: {exc}", file=sys.stderr)
            if attempt >= total:
                break
            delay = backoff_seconds(attempt, initial_sleep_s, max_sleep_s)
            print(f"Retrying in {delay:.0f}s...", file=sys.stderr)
            sleeper(delay)
    raise PublishError(f"Failed to publish {tag} after {total} attempts: {last_error}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--prerelease", action="store_true")
    parser.add_argument("--file", dest="files", action="append", required=True)
    parser.add_argument("--notes-file", dest="notes_file", default=None)
    parser.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    notes = Path(args.notes_file) if args.notes_file else None
    try:
        publish_with_retries(
            tag=args.tag,
            title=args.title,
            target=args.target,
            prerelease=bool(args.prerelease),
            files=[Path(p) for p in args.files],
            notes_file=notes,
            attempts=args.attempts,
        )
    except PublishError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
