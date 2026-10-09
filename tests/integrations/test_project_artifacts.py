from __future__ import annotations

import hashlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock
from unittest.mock import patch

from forma_core.persistence.project_artifacts import (
    ProjectArtifactStorage,
    ProjectArtifactStorageError,
    project_artifact_storage_key,
)
from forma_core.workspaces.projects.manifest import validate_artifact_references


class ProjectArtifactStorageTests(unittest.TestCase):
    @staticmethod
    def local_storage(directory: str) -> ProjectArtifactStorage:
        return ProjectArtifactStorage({
            "enabled": True, "backend": "local", "directory": Path(directory),
            "bucket": "unused", "max_bytes": 1024,
        })

    def test_local_replay_preserves_verified_blob_with_open_reader(self) -> None:
        content = b"immutable artifact"
        sha256 = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            storage = self.local_storage(directory)
            storage.put("project-a", sha256, content, "application/octet-stream")
            target = Path(directory) / project_artifact_storage_key("project-a", sha256)
            # A Windows reader can deny replacement even though the stored blob
            # already satisfies this content-addressed put. No rewrite is needed.
            with target.open("rb") as reader, patch.object(
                Path, "replace", side_effect=AssertionError("Verified content must not be replaced")
            ):
                stored = storage.put("project-a", sha256, content, "application/octet-stream")
                self.assertEqual(content, reader.read())
            self.assertEqual(sha256, stored.sha256)
            self.assertEqual([target], list(target.parent.iterdir()))

    def test_concurrent_local_publish_accepts_verified_winner(self) -> None:
        content = b"one content-addressed blob"
        sha256 = hashlib.sha256(content).hexdigest()
        writers = 8
        ready = Barrier(writers, timeout=15)
        publishing = Lock()
        replace = Path.replace
        denied: list[Path] = []

        def windows_replace(source: Path, target: Path) -> Path:
            # Force every writer past the initial cache miss. Once one writer
            # publishes, emulate Windows refusing replacement of an open target.
            ready.wait()
            with publishing:
                if target.exists():
                    denied.append(source)
                    raise PermissionError(13, "Destination is open by a concurrent reader", str(target))
                return replace(source, target)

        with tempfile.TemporaryDirectory() as directory:
            def write(_: int):
                # Separate instances exercise the filesystem boundary rather than
                # relying on a lock attached to one storage or library instance.
                return self.local_storage(directory).put("project-a", sha256, content, "application/octet-stream")

            with patch.object(Path, "replace", windows_replace), ThreadPoolExecutor(max_workers=writers) as pool:
                stored = list(pool.map(write, range(writers)))
            self.assertEqual(writers, len(stored))
            self.assertTrue(all(item.sha256 == sha256 for item in stored))
            self.assertEqual(writers - 1, len(denied))
            target = Path(directory) / project_artifact_storage_key("project-a", sha256)
            self.assertEqual(content, target.read_bytes())
            self.assertEqual([target], list(target.parent.iterdir()))

    def test_denied_publish_requires_verified_destination(self) -> None:
        content = b"expected artifact bytes"
        sha256 = hashlib.sha256(content).hexdigest()
        for existing in (None, b"corrupt bytes", content):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as directory:
                storage = self.local_storage(directory)
                target = Path(directory) / project_artifact_storage_key("project-a", sha256)
                target.parent.mkdir(parents=True)
                if existing is not None:
                    target.write_bytes(existing)
                failure = PermissionError(13, "Publication denied", str(target))
                # Even matching content is insufficient if it cannot be read and
                # verified; retain the original publication failure in that case.
                read_bytes = Path.read_bytes

                def read(path: Path) -> bytes:
                    if existing == content:
                        raise PermissionError(13, "Verification denied", str(path))
                    return read_bytes(path)

                with patch.object(Path, "read_bytes", read), patch.object(Path, "replace", side_effect=failure):
                    with self.assertRaises(PermissionError) as raised:
                        storage.put("project-a", sha256, content, "application/octet-stream")
                self.assertIs(failure, raised.exception)
                self.assertEqual([] if existing is None else [target], list(target.parent.iterdir()))
                if existing is not None:
                    self.assertEqual(existing, target.read_bytes())

    def test_partial_local_write_closes_and_removes_temporary_file(self) -> None:
        content = b"artifact bytes"
        sha256 = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            storage = self.local_storage(directory)
            temporary_file = tempfile.NamedTemporaryFile
            opened = []
            failure = OSError("Disk write failed")

            def failing_file(*args, **kwargs):
                handle = temporary_file(*args, **kwargs)
                opened.append(handle)
                write = handle.write

                def partial_write(data: bytes) -> None:
                    write(data[:3])
                    raise failure

                handle.write = partial_write
                return handle

            with patch("forma_core.persistence.project_artifacts.tempfile.NamedTemporaryFile", failing_file):
                with self.assertRaises(OSError) as raised:
                    storage.put("project-a", sha256, content, "application/octet-stream")
            self.assertIs(failure, raised.exception)
            self.assertTrue(all(handle.closed for handle in opened))
            self.assertEqual([], [p for p in Path(directory).rglob("*") if p.is_file()])

    def test_local_storage_round_trip_is_project_scoped(self) -> None:
        content = b"private project artifact"
        sha256 = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            storage = ProjectArtifactStorage(
                {
                    "enabled": True,
                    "backend": "local",
                    "directory": Path(directory),
                    "bucket": "unused",
                    "max_bytes": 1024,
                }
            )

            stored = storage.put("project-a", sha256, content, "application/octet-stream")
            restored = storage.get("project-a", sha256, "application/octet-stream")

            self.assertEqual(content, restored.content)
            self.assertTrue((Path(directory) / Path(*project_artifact_storage_key("project-a", sha256).split("/"))).is_file())
            with self.assertRaises(FileNotFoundError):
                storage.get("project-b", sha256, "application/octet-stream")
            self.assertEqual(sha256, stored.sha256)
            with self.assertRaisesRegex(ProjectArtifactStorageError, "does not match"):
                storage.put("project-a", "0" * 64, content, "application/octet-stream")
            self.assertEqual(1, storage.delete_project("project-a"))
            with self.assertRaises(FileNotFoundError):
                storage.get("project-a", sha256, "application/octet-stream")
            self.assertEqual(0, storage.delete_project("project-a"))

    def test_supabase_contains_matches_object_under_folder_listing(self) -> None:
        content = b"supabase-backed artifact"
        sha256 = hashlib.sha256(content).hexdigest()
        key = project_artifact_storage_key("project-sb", sha256)
        folder, _, name = key.rpartition("/")

        class FakeSupabaseBucket:
            """Reproduce the storage list quirk: a prefix equal to an object
            key behaves like a folder and only lists its children."""

            def __init__(self) -> None:
                self.objects: dict[str, bytes] = {}

            def upload(self, path: str, data: bytes, file_options: dict | None = None) -> None:
                self.objects[path] = bytes(data)

            def update(self, path: str, data: bytes, file_options: dict | None = None) -> None:
                self.objects[path] = bytes(data)

            def download(self, path: str) -> bytes:
                if path not in self.objects:
                    raise FileNotFoundError(path)
                return self.objects[path]

            def list(self, path: str, options: dict | None = None) -> list[dict]:
                prefix = (path or "").rstrip("/") + "/"
                children: list[dict] = []
                for object_key in self.objects:
                    if object_key.startswith(prefix):
                        remainder = object_key[len(prefix):]
                        children.append({"name": remainder.split("/", 1)[0]})
                return children

        storage = ProjectArtifactStorage(
            {
                "enabled": True,
                "backend": "supabase",
                "bucket": "cli-project-artifacts",
                "max_bytes": 1024,
            }
        )
        fake_bucket = FakeSupabaseBucket()
        storage._supabase_bucket = lambda: fake_bucket  # type: ignore[method-assign]

        storage.put("project-sb", sha256, content, "application/octet-stream")

        self.assertTrue(storage.contains("project-sb", sha256))
        self.assertFalse(storage.contains("project-sb", "0" * 64))

    def test_artifact_declarations_require_integrity_and_reject_traversal(self) -> None:
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            validate_artifact_references([{"path": "assembly.step", "media_type": "model/step"}])
        with self.assertRaisesRegex(ValueError, "escape"):
            validate_artifact_references(
                [{"path": "../secret.txt", "sha256": "0" * 64, "media_type": "text/plain"}]
            )
        with self.assertRaisesRegex(ValueError, "duplicated"):
            validate_artifact_references(
                [
                    {"path": "Assembly.step", "sha256": "0" * 64, "media_type": "model/step"},
                    {"path": "assembly.step", "sha256": "1" * 64, "media_type": "model/step"},
                ]
            )


if __name__ == "__main__":
    unittest.main()
