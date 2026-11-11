"""Confirmed local-drive file operations, staged writes, and bounded ZIP handling."""
from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import struct
import tempfile
import time
import zipfile
import zlib

from .files import FileSearchService
from .models import CommandResult
from .rollback import RollbackManager


MAX_ENTRIES = 5000
MAX_BYTES = 512 * 1024 * 1024
MAX_SECONDS = 60
MAX_ZIP_DEPTH = 64
ARCHIVE_ERRORS = (OSError, ValueError, RuntimeError, EOFError,
                  zipfile.BadZipFile, zipfile.LargeZipFile, zlib.error)
PRIVATE_NAMES = {".ssh", ".aws", ".azure", ".codex", ".git", ".venv", "appdata",
                 "$recycle.bin", "system volume information"}


class FileOperationCancelled(RuntimeError):
    pass


class FileOperationTimeout(RuntimeError):
    pass


def file_operation(fn):
    @wraps(fn)
    def run(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except ARCHIVE_ERRORS as exc:
            metadata = {"operation": fn.__name__, "retryable": False}
            if isinstance(exc, FileOperationCancelled):
                metadata["cancelled"] = True
            elif isinstance(exc, FileOperationTimeout):
                metadata["budget_exhausted"] = True
            return CommandResult(False, f"{fn.__name__}: {exc}",
                                 metadata=metadata)
    return run


class LocalFileActions:
    def __init__(self, dry_run=False, *, folders=None, cancelled=None):
        self.dry_run = dry_run
        self.folders = folders if folders is not None else FileSearchService._known_folders()
        self.cancelled = cancelled or (lambda: False)

    @staticmethod
    def explicit_path(value: str) -> bool:
        return bool(re.match(r"^(?:[A-Za-z]:|[/\\~]|(?:Desktop|Documents|Downloads|Pictures)(?:[/\\]|$))", value, re.I))

    @staticmethod
    def _name(name: str) -> None:
        if (not name or name in {".", ".."} or name.endswith((" ", "."))
                or any(ord(c) < 32 or c in '<>:"|?*\\/' for c in name)
                or PureWindowsPath(name).is_reserved()):
            raise ValueError("Invalid Windows file/folder name.")
        if name.casefold() in PRIVATE_NAMES or name.casefold().startswith(".env"):
            raise ValueError("Private configuration and system folders need separate review.")

    def path(self, value: str, *, must_exist=False, mutate_root=False) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Specify an explicit local path.")
        raw = value.strip().strip('"')
        if raw.startswith(("\\\\", "//")) or ":" in raw[2:]:
            raise ValueError("Network/device paths and alternate data streams are not allowed.")
        first, *tail = re.split(r"[/\\]", raw, maxsplit=1)
        if first.casefold() in self.folders:
            raw = str(self.folders[first.casefold()] / tail[0]) if tail else str(self.folders[first.casefold()])
        candidate = Path(raw).expanduser()
        if candidate.drive and not candidate.is_absolute():
            raise ValueError("Use an absolute drive path, not a drive-relative path.")
        candidate = candidate if candidate.is_absolute() else Path.cwd() / candidate
        for part in candidate.parts[1:]:
            self._name(part)
        for item in (candidate, *candidate.parents):
            try:
                attrs = item.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(attrs.st_mode) or getattr(attrs, "st_file_attributes", 0) & 0x400:
                raise ValueError("Symlinks, junctions and cloud placeholders need separate review.")
        candidate = candidate.resolve(strict=must_exist)
        protected = [Path(os.environ.get("WINDIR", r"C:\Windows")),
                     Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
                     Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
                     Path(os.environ.get("ProgramData", r"C:\ProgramData"))]
        if any(candidate == p.resolve() or p.resolve() in candidate.parents for p in protected):
            raise ValueError("Windows, program installation and system data folders are protected.")
        roots = {Path(candidate.anchor), Path.home().resolve(), Path.cwd().resolve(),
                 *(Path(folder).resolve() for folder in self.folders.values())}
        if mutate_root and candidate in roots:
            raise ValueError("Cannot rename or move a drive, user, workspace or known-folder root.")
        return candidate

    def _tick(self, deadline):
        if self.cancelled():
            raise FileOperationCancelled("Operation cancelled; no completed change is undone.")
        if time.monotonic() > deadline:
            raise FileOperationTimeout("The 60-second operation limit was reached.")

    def _tree(self, source: Path, deadline):
        pending, entries, total = [source], [], 0
        while pending:
            self._tick(deadline)
            path = self.path(str(pending.pop()), must_exist=True)
            attrs = path.stat()
            if not (stat.S_ISDIR(attrs.st_mode) or stat.S_ISREG(attrs.st_mode)):
                raise ValueError("Only ordinary files and folders are supported.")
            entries.append((path, attrs.st_size if path.is_file() else 0))
            total += entries[-1][1]
            if len(entries) > MAX_ENTRIES or total > MAX_BYTES:
                raise ValueError("Operation exceeds 5000 entries or 512 MB.")
            if path.is_dir():
                with os.scandir(path) as children:
                    for child in children:
                        self._tick(deadline)
                        pending.append(Path(child.path))
                        if len(pending) + len(entries) > MAX_ENTRIES:
                            raise ValueError("Operation exceeds 5000 entries.")
        return entries

    def _copy_stream(self, source, output, deadline, *, limit=MAX_BYTES, digest=None):
        count = 0
        while True:
            self._tick(deadline)
            chunk = source.read(64 * 1024)
            if not chunk:
                return count
            count += len(chunk)
            if count > limit:
                raise ValueError("File expanded or grew beyond the allowed size.")
            if digest is not None:
                digest.update(chunk)
            output.write(chunk)

    def _destination(self, value):
        destination = self.path(value)
        if destination.exists():
            raise ValueError("Destination already exists; nothing will be overwritten.")
        if not destination.parent.is_dir():
            raise ValueError("Destination parent does not exist. Create that folder first.")
        return destination

    def _publish(self, staged, destination, deadline):
        self._tick(deadline)
        self._destination(str(destination))
        if os.name != "nt":
            raise ValueError("No-overwrite publishing currently requires Windows.")
        staged.rename(destination)  # Windows rename fails if destination exists.

    @file_operation
    def inspect_local_path(self, path: str) -> CommandResult:
        target = self.path(path)
        self._tick(time.monotonic() + MAX_SECONDS)
        observed = {"path": str(target), "observed_at": datetime.now(timezone.utc).isoformat(),
                    "content_read": False}
        try:
            attrs = target.stat()
        except FileNotFoundError:
            return CommandResult(True, f"Path does not exist: {target}",
                                 metadata={**observed, "exists": False, "kind": "missing"})
        if not (stat.S_ISREG(attrs.st_mode) or stat.S_ISDIR(attrs.st_mode)):
            raise ValueError("Only ordinary files and folders can be inspected.")
        kind = "folder" if stat.S_ISDIR(attrs.st_mode) else "file"
        modified = datetime.fromtimestamp(attrs.st_mtime, timezone.utc).isoformat()
        size = attrs.st_size if kind == "file" else None
        detail = f" ({size} bytes)" if size is not None else ""
        return CommandResult(True, f"{kind.title()} exists: {target}{detail}. Last modified (UTC): {modified}",
                             metadata={**observed, "exists": True, "kind": kind,
                                       "size_bytes": size, "modified_at": modified})

    def _verify_creation(self, target, kind, *, expected_bytes=None):
        if self.dry_run:
            return {"dry_run": True, "completion_verified": False}
        inspection = self.inspect_local_path(str(target))
        observed = inspection.metadata
        verified = (inspection.ok and observed.get("exists") is True and observed.get("kind") == kind
                    and (expected_bytes is None or observed.get("size_bytes") == expected_bytes))
        return {"completion_verified": verified, "outcome_uncertain": not verified,
                "verification_scope": "existence_type_and_size" if expected_bytes is not None else "existence_and_type",
                "path_observation": observed}

    @staticmethod
    def _stamp(attrs):
        return (attrs.st_dev, attrs.st_ino, attrs.st_size, attrs.st_mtime_ns, attrs.st_ctime_ns)

    def _verify_copy(self, destination, expected_digest, expected_bytes, deadline):
        target = self.path(str(destination), must_exist=True)
        before = target.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_size != expected_bytes:
            raise ValueError("Copied destination has a different type or size.")
        observed_digest = hashlib.sha256()
        with target.open("rb") as reader:
            if self._stamp(os.fstat(reader.fileno())) != self._stamp(before):
                raise ValueError("Copied destination changed before verification.")
            remaining = expected_bytes
            while True:
                self._tick(deadline)
                chunk = reader.read(min(64 * 1024, remaining + 1))
                if not chunk:
                    break
                remaining -= len(chunk)
                if remaining < 0:
                    raise ValueError("Copied destination grew during verification.")
                observed_digest.update(chunk)
            if self._stamp(os.fstat(reader.fileno())) != self._stamp(before):
                raise ValueError("Copied destination changed during verification.")
        self.path(str(target), must_exist=True)
        if (self._stamp(target.stat()) != self._stamp(before) or remaining != 0
                or observed_digest.digest() != expected_digest):
            raise ValueError("Copied contents did not match the source stream.")
        return {"path": str(target), "size_bytes": before.st_size, "sha256_matches": True,
                "observed_at": datetime.now(timezone.utc).isoformat()}

    @staticmethod
    def _unverified_change(message, metadata, scope):
        return CommandResult(False, message + " Inspect the source and destination before retrying. Nothing was automatically undone.",
            metadata={**metadata, "completion_verified": False, "outcome_uncertain": True,
                      "change_completed": None, "retryable": False, "verification_scope": scope})

    @file_operation
    def create_local_folder(self, path: str) -> CommandResult:
        target = self.path(path)
        self._tick(time.monotonic() + MAX_SECONDS)
        if target.exists() and not target.is_dir():
            raise ValueError("A file already exists at the requested path.")
        existed = target.is_dir()
        if not self.dry_run:
            target.mkdir(parents=True, exist_ok=True)
        verification = self._verify_creation(target, "folder")
        ok = self.dry_run or verification["completion_verified"]
        return CommandResult(ok, (f"{'Would create' if self.dry_run else 'Folder ready:'} {target}" if ok else
                             f"Folder creation was attempted but could not be verified: {target}. No automatic retry."),
                             metadata={"path": str(target), "created": not self.dry_run and not existed and ok, **verification})

    @file_operation
    def recycle_local_path(self, path: str) -> CommandResult:
        if not self.explicit_path(path):
            raise ValueError("Recycling requires an absolute path or a known-folder path.")
        source = self.path(path, must_exist=True, mutate_root=True)
        if source in Path.cwd().resolve().parents:
            raise ValueError("Workspace ancestor folders are protected.")
        deadline = time.monotonic() + MAX_SECONDS
        self._tree(source, deadline)
        identity = self._identity(source)
        if self.dry_run:
            return CommandResult(True, f"Would send to the Recycle Bin: {source}")
        if os.name != "nt":
            raise ValueError("Recycle-only deletion requires Windows.")
        try:
            from .recycle import recycle_path
            self._tick(deadline)
            self.path(str(source), must_exist=True, mutate_root=True)
            if self._identity(source) != identity:
                raise ValueError("Source changed; recycling refused.")
            recycle_path(source)
        except ImportError:
            return CommandResult(False, "Install the files extra (pywin32 and send2trash) for recycling.")
        if source.exists():
            return CommandResult(False, "The path still exists; recycling could not be verified.")
        return CommandResult(True, f"Sent to the Recycle Bin: {source}. Restore it from Windows Recycle Bin.",
            metadata={"path": str(source), "recycled": True, "permanent_delete": False,
                      "verification": "source_absent_after_recycle"})

    @file_operation
    def create_local_file(self, path: str, content: str = "") -> CommandResult:
        target = self._destination(path)
        encoded = content.encode("utf-8")
        if len(encoded) > 1_000_000:
            raise ValueError("Text exceeds the 1 MB limit.")
        deadline = time.monotonic() + MAX_SECONDS
        if not self.dry_run:
            with tempfile.TemporaryDirectory(prefix=".jarvis-", dir=target.parent) as staging:
                staged = Path(staging) / "file"
                staged.write_bytes(encoded)
                self._publish(staged, target, deadline)
        verification = self._verify_creation(target, "file", expected_bytes=len(encoded))
        ok = self.dry_run or verification["completion_verified"]
        return CommandResult(ok, (f"{'Would create' if self.dry_run else 'Created'} {target}" if ok else
                             f"File creation was attempted but could not be verified: {target}. No automatic retry."),
                             metadata={"path": str(target), **verification})

    @file_operation
    def rename_local_path(self, path: str, new_name: str) -> CommandResult:
        self._name(new_name)
        source = self.path(path, must_exist=True, mutate_root=True)
        return self.move_local_path(str(source), str(source.with_name(new_name)))

    @file_operation
    def move_local_path(self, source: str, destination: str) -> CommandResult:
        return self._move(source, destination)

    @staticmethod
    def _identity(path: Path) -> dict:
        attrs = path.stat()
        if not attrs.st_ino:
            raise ValueError("This filesystem does not expose a stable file identity for undo.")
        return {"device": attrs.st_dev, "inode": attrs.st_ino,
                "created_ns": getattr(attrs, "st_birthtime_ns", attrs.st_ctime_ns),
                "kind": stat.S_IFMT(attrs.st_mode)}

    @file_operation
    def restore_move(self, payload: dict) -> CommandResult:
        """Internal rollback handler; never registers an inverse history entry."""
        if (not isinstance(payload, dict) or payload.get("version") != 1
                or not isinstance(payload.get("identity"), dict)):
            raise ValueError("Invalid file undo record; nothing was moved.")
        for key in ("source", "destination"):
            value = payload.get(key)
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise ValueError("Undo requires the originally recorded absolute paths.")
        identity = payload["identity"]
        if (set(identity) != {"device", "inode", "created_ns", "kind"}
                or any(type(value) is not int for value in identity.values())):
            raise ValueError("Invalid file identity in undo record.")
        return self._move(payload["destination"], payload["source"], expected_identity=identity,
                          record_undo=False)

    def _move(self, source: str, destination: str, *, expected_identity=None, record_undo=True) -> CommandResult:
        source = self.path(source, must_exist=True, mutate_root=True)
        destination = self._destination(destination)
        deadline = time.monotonic() + MAX_SECONDS
        if source == destination or source in destination.parents:
            raise ValueError("Cannot move a folder inside itself.")
        if source.drive.casefold() != destination.drive.casefold():
            raise ValueError("Cross-drive moves are not supported; copy the file instead.")
        if not (source.is_file() or source.is_dir()):
            raise ValueError("Only ordinary files or folders can be moved.")
        identity = self._identity(source)
        if expected_identity is not None and identity != expected_identity:
            raise ValueError("The file/folder was replaced since the move. Undo refused; history retained.")
        metadata = {"source": str(source), "destination": str(destination), "overwritten": False,
                    "undo_available": False, "change_completed": False}
        scope = "source_absent_and_destination_identity"
        metadata.update(dry_run=self.dry_run, completion_verified=False, verification_scope=scope)
        warning = ""
        if not self.dry_run:
            self.path(str(source), must_exist=True, mutate_root=True)
            if self._identity(source) != identity:
                raise ValueError("Source identity changed before the move; nothing was moved.")
            try:
                self._publish(source, destination, deadline)
                self._tick(deadline)
                self.path(str(source))
                self.path(str(destination), must_exist=True)
                if source.exists() or self._identity(destination) != identity:
                    raise ValueError("Move postconditions did not match.")
            except (OSError, ValueError, RuntimeError):
                return self._unverified_change("Move was attempted but its result could not be verified.", metadata, scope)
            metadata["change_completed"] = True
            metadata["completion_verified"] = True
            metadata["move_observation"] = {"source_absent": True, "destination_identity_matches": True,
                "observed_at": datetime.now(timezone.utc).isoformat()}
            if record_undo:
                try:
                    RollbackManager().push(f"Move {source} -> {destination}", "local_path_move",
                                           {"version": 1, "source": str(source),
                                            "destination": str(destination), "identity": identity})
                    metadata["undo_available"] = True
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    warning = " Move completed, but undo history could not be saved."
                    metadata["undo_history_error"] = str(exc)
        verb = "Would move" if self.dry_run else ("Moved" if record_undo else "Restored")
        return CommandResult(True, f"{verb} {source} to {destination}.{warning}", metadata=metadata)

    @file_operation
    def copy_local_file(self, source: str, destination: str) -> CommandResult:
        source = self.path(source, must_exist=True)
        destination = self._destination(destination)
        if not source.is_file():
            raise ValueError("Copy currently supports one file; use ZIP for a folder.")
        if source.stat().st_size > MAX_BYTES:
            raise ValueError("File exceeds 512 MB.")
        deadline = time.monotonic() + MAX_SECONDS
        metadata = {"source": str(source), "destination": str(destination), "dry_run": self.dry_run,
                    "completion_verified": False, "change_completed": False}
        scope = "stable_source_stream_and_destination_sha256"
        metadata["verification_scope"] = scope
        attempted = False
        if not self.dry_run:
            try:
                with tempfile.TemporaryDirectory(prefix=".jarvis-", dir=destination.parent) as staging:
                    staged = Path(staging) / "file"
                    before = self.path(str(source), must_exist=True).stat()
                    source_digest = hashlib.sha256()
                    with source.open("rb") as reader, staged.open("xb") as writer:
                        if self._stamp(os.fstat(reader.fileno())) != self._stamp(before):
                            raise ValueError("Source changed before copying.")
                        copied = self._copy_stream(reader, writer, deadline, limit=MAX_BYTES, digest=source_digest)
                        if self._stamp(os.fstat(reader.fileno())) != self._stamp(before):
                            raise ValueError("Source changed while copying; destination was not published.")
                    self.path(str(source), must_exist=True)
                    if self._stamp(source.stat()) != self._stamp(before) or copied != before.st_size:
                        raise ValueError("Source changed while copying; destination was not published.")
                    attempted = True
                    self._publish(staged, destination, deadline)
                    observation = self._verify_copy(destination, source_digest.digest(), copied, deadline)
                metadata.update(completion_verified=True, change_completed=True, copy_observation=observation)
            except (OSError, ValueError, RuntimeError):
                if attempted:
                    return self._unverified_change("Copy was attempted but its contents could not be verified.", metadata, scope)
                raise
        return CommandResult(True, f"{'Would copy' if self.dry_run else 'Copied'} {source} to {destination}",
                             metadata=metadata)

    @file_operation
    def create_zip(self, source: str, destination: str) -> CommandResult:
        source = self.path(source, must_exist=True)
        destination = self._destination(destination)
        if destination.suffix.casefold() != ".zip" or source in destination.parents:
            raise ValueError("Choose a .zip destination outside the source folder.")
        deadline = time.monotonic() + MAX_SECONDS
        snapshot = self._tree_snapshot(source, deadline)
        if len(snapshot) + 1 > MAX_ENTRIES:
            raise ValueError("ZIP extraction would exceed the entry limit including its root folder.")
        metadata = {"source": str(source), "destination": str(destination), "entries": len(snapshot),
                    "dry_run": self.dry_run, "completion_verified": False, "change_completed": False}
        scope = "stable_source_tree_and_archive_crc_sha256"
        metadata["verification_scope"] = scope
        attempted = False
        if not self.dry_run:
            try:
                with tempfile.TemporaryDirectory(prefix=".jarvis-", dir=destination.parent) as staging:
                    staged = Path(staging) / "archive.zip"
                    remaining, manifest = MAX_BYTES, {}
                    with zipfile.ZipFile(staged, "x", compression=zipfile.ZIP_DEFLATED) as archive:
                        for path, (is_dir, stamp) in snapshot.items():
                            self._tick(deadline)
                            self.path(str(path), must_exist=True)
                            if self._stamp(path.stat()) != stamp:
                                raise ValueError("Source changed before archiving.")
                            name = path.relative_to(source.parent).as_posix()
                            if len(name.split("/")) > MAX_ZIP_DEPTH:
                                raise ValueError("ZIP nesting exceeds 64 levels.")
                            if is_dir:
                                archive.writestr(name + "/", b"")
                                manifest[name + "/"] = (True, 0, None)
                            else:
                                digest = hashlib.sha256()
                                with path.open("rb") as reader, archive.open(name, "w") as writer:
                                    if self._stamp(os.fstat(reader.fileno())) != stamp:
                                        raise ValueError("Source changed before archiving.")
                                    copied = self._copy_stream(reader, writer, deadline, limit=min(remaining, stamp[2]), digest=digest)
                                    if self._stamp(os.fstat(reader.fileno())) != stamp or copied != stamp[2]:
                                        raise ValueError("Source changed while archiving.")
                                remaining -= copied
                                manifest[name] = (False, copied, digest.digest())
                    self._verify_archive(staged, manifest, deadline)
                    if self._tree_snapshot(source, deadline) != snapshot:
                        raise ValueError("Source tree changed; ZIP was not published.")
                    attempted = True
                    self._publish(staged, destination, deadline)
                    observation = self._verify_archive(destination, manifest, deadline)
                metadata.update(completion_verified=True, change_completed=True, archive_observation=observation)
            except ARCHIVE_ERRORS:
                if attempted:
                    return self._unverified_change("ZIP creation was attempted but its contents could not be verified.", metadata, scope)
                raise
        return CommandResult(True, f"{'Would create ZIP' if self.dry_run else 'Created ZIP'} {destination}",
                             metadata=metadata)

    def _tree_snapshot(self, root, deadline):
        snapshot = {}
        for path, _ in self._tree(root, deadline):
            self._tick(deadline)
            attrs = self.path(str(path), must_exist=True).stat()
            if not (stat.S_ISDIR(attrs.st_mode) or stat.S_ISREG(attrs.st_mode)):
                raise ValueError("Source tree contains a non-ordinary path.")
            snapshot[path] = (stat.S_ISDIR(attrs.st_mode), self._stamp(attrs))
        return snapshot

    @contextmanager
    def _bounded_zip(self, source, deadline):
        source = self.path(str(source), must_exist=True)
        before = source.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
            raise ValueError("ZIP must be an ordinary file no larger than 512 MB.")
        with source.open("rb") as reader:
            def unchanged():
                self._tick(deadline)
                self.path(str(source), must_exist=True)
                if (self._stamp(os.fstat(reader.fileno())) != self._stamp(before)
                        or self._stamp(source.stat()) != self._stamp(before)):
                    raise ValueError("ZIP changed during the operation.")

            unchanged()
            # Bound central-directory allocation before ZipFile loads its members.
            tail_start = max(0, before.st_size - 65557)
            reader.seek(tail_start)
            tail = reader.read(65557)
            offset = tail.rfind(b"PK\x05\x06")
            if offset < 0 or len(tail) - offset < 22:
                raise ValueError("Invalid ZIP end record.")
            _, disk, directory_disk, disk_entries, count, directory_size, directory_offset, comment = struct.unpack_from("<4s4H2LH", tail, offset)
            if (disk or directory_disk or disk_entries != count or count > MAX_ENTRIES
                    or directory_size > 4 * 1024 * 1024 or directory_offset == 0xFFFFFFFF
                    or (offset >= 20 and tail[offset - 20:offset - 16] == b"PK\x06\x07")
                    or directory_offset + directory_size > tail_start + offset
                    or offset + 22 + comment != len(tail)):
                raise ValueError("ZIP directory exceeds limits or uses unsupported split/ZIP64 layout.")
            with zipfile.ZipFile(reader) as archive:
                members = archive.infolist()
                if len(members) != count or sum(item.file_size for item in members) > MAX_BYTES:
                    raise ValueError("ZIP exceeds entry/expanded size limits or has inconsistent counts.")
                unchanged()
                yield archive, unchanged
                unchanged()

    def _hash_zip_member(self, archive, item, deadline):
        digest, remaining = hashlib.sha256(), item.file_size
        with archive.open(item) as reader:
            while True:
                self._tick(deadline)
                chunk = reader.read(min(64 * 1024, remaining + 1))
                if not chunk:
                    break
                remaining -= len(chunk)
                if remaining < 0:
                    raise ValueError("ZIP member exceeded its declared size.")
                digest.update(chunk)
        if remaining:
            raise ValueError("ZIP member was truncated.")
        return digest.digest()

    def _verify_archive(self, target, manifest, deadline):
        with self._bounded_zip(target, deadline) as (archive, _):
            members = archive.infolist()
            if len(members) != len(manifest) or {item.orig_filename for item in members} != set(manifest):
                raise ValueError("ZIP member list did not match the source tree.")
            for item in members:
                is_dir, size, digest = manifest[item.orig_filename]
                if item.is_dir() != is_dir or item.file_size != size:
                    raise ValueError("ZIP member type or size did not match.")
                observed = self._hash_zip_member(archive, item, deadline)
                if not is_dir and observed != digest:
                    raise ValueError("ZIP member contents did not match the source stream.")
        return {"entries": len(manifest), "size_bytes": sum(row[1] for row in manifest.values()),
                "crc_matches": True, "sha256_matches": True,
                "observed_at": datetime.now(timezone.utc).isoformat()}

    def _verify_extracted(self, target, manifest, deadline):
        snapshot = self._tree_snapshot(target, deadline)
        observed = {path.relative_to(target).as_posix().casefold(): (path, is_dir)
                    for path, (is_dir, _) in snapshot.items()}
        if len(observed) != len(snapshot) or set(observed) != set(manifest):
            raise ValueError("Extracted paths did not match the ZIP contents.")
        for key, (is_dir, size, digest) in manifest.items():
            self._tick(deadline)
            path, actual_dir = observed[key]
            if actual_dir != is_dir:
                raise ValueError("Extracted path has the wrong type.")
            if not is_dir:
                self._verify_copy(path, digest, size, deadline)
        if self._tree_snapshot(target, deadline) != snapshot:
            raise ValueError("Extracted tree changed during verification.")
        return {"paths_including_root": len(manifest), "sha256_matches": True,
                "size_bytes": sum(row[1] for row in manifest.values()),
                "observed_at": datetime.now(timezone.utc).isoformat()}

    @file_operation
    def extract_zip(self, source: str, destination: str) -> CommandResult:
        source = self.path(source, must_exist=True)
        destination = self._destination(destination)
        deadline = time.monotonic() + MAX_SECONDS
        metadata = {"source": str(source), "destination": str(destination), "dry_run": self.dry_run,
                    "completion_verified": False, "change_completed": False}
        scope = "stable_zip_stream_and_extracted_tree_sha256"
        metadata["verification_scope"] = scope
        attempted = False
        try:
            with self._bounded_zip(source, deadline) as (archive, unchanged):
                plan, kinds = self._extraction_plan(archive, deadline)
                metadata["entries"] = len(plan)
                if not self.dry_run:
                    with tempfile.TemporaryDirectory(prefix=".jarvis-", dir=destination.parent) as staging:
                        payload = Path(staging) / "extracted"
                        payload.mkdir()
                        manifest = {".": (True, 0, None), **{key: (kind, 0, None) for key, kind in kinds.items()}}
                        remaining = MAX_BYTES
                        for item, parts in plan:
                            self._tick(deadline)
                            target = payload.joinpath(*parts)
                            if item.is_dir():
                                self._hash_zip_member(archive, item, deadline)
                                target.mkdir(parents=True, exist_ok=True)
                            else:
                                target.parent.mkdir(parents=True, exist_ok=True)
                                digest = hashlib.sha256()
                                with archive.open(item) as reader, target.open("xb") as writer:
                                    copied = self._copy_stream(reader, writer, deadline, limit=min(remaining, item.file_size), digest=digest)
                                if copied != item.file_size:
                                    raise ValueError("Extracted member has the wrong size.")
                                remaining -= copied
                                manifest["/".join(parts).casefold()] = (False, copied, digest.digest())
                        self._verify_extracted(payload, manifest, deadline)
                        unchanged()
                        attempted = True
                        self._publish(payload, destination, deadline)
                        observation = self._verify_extracted(destination, manifest, deadline)
            if not self.dry_run:
                metadata.update(completion_verified=True, change_completed=True, extraction_observation=observation)
        except ARCHIVE_ERRORS:
            if attempted:
                return self._unverified_change("ZIP extraction was attempted but its contents could not be verified.", metadata, scope)
            raise
        return CommandResult(True, f"{'Would extract ZIP to' if self.dry_run else 'Extracted ZIP to'} {destination}",
                             metadata=metadata)

    def _extraction_plan(self, archive, deadline):
        seen, kinds, plan = set(), {}, []
        for item in archive.infolist():
            self._tick(deadline)
            name = item.orig_filename
            if not name or name.startswith("/") or "\\" in name or "\x00" in name:
                raise ValueError("Unsafe ZIP member path.")
            parts = name.rstrip("/").split("/")
            if len(parts) > MAX_ZIP_DEPTH:
                raise ValueError("ZIP nesting exceeds 64 levels.")
            for part in parts:
                self._name(part)
            mode = item.external_attr >> 16
            if stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR} or item.flag_bits & 1:
                raise ValueError("Linked, special or encrypted ZIP entries are not supported.")
            if item.is_dir() and item.file_size:
                raise ValueError("ZIP directory entries must be empty.")
            key = "/".join(parts).casefold()
            if key in seen or (key in kinds and kinds[key] != item.is_dir()):
                raise ValueError("ZIP contains duplicate or conflicting paths.")
            seen.add(key)
            kinds[key] = item.is_dir()
            for index in range(1, len(parts)):
                parent = "/".join(parts[:index]).casefold()
                if kinds.get(parent) is False:
                    raise ValueError("ZIP has conflicting file and directory paths.")
                kinds[parent] = True
            if len(kinds) + 1 > MAX_ENTRIES:
                raise ValueError("ZIP exceeds 5000 paths including implicit directories and the root.")
            plan.append((item, parts))
        return plan, kinds

    @file_operation
    def list_local_folder(self, path: str) -> CommandResult:
        folder = self.path(path, must_exist=True)
        entries = []
        with os.scandir(folder) as items:
            for item in items:
                if len(entries) == 100:
                    break
                entries.append({"name": item.name, "path": item.path, "is_directory": item.is_dir(follow_symlinks=False)})
        return CommandResult(True, "\n".join(item["name"] for item in entries) or "Folder is empty.",
                             metadata={"path": str(folder), "entries": entries, "partial": len(entries) == 100})
