from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from .models import CandidateChange, FilePatch


def apply_file_patch(root: Path, patch: FilePatch) -> None:
    path = root / patch.path
    original = path.read_text(encoding="utf-8")
    if patch.old_text not in original:
        raise ValueError(f"Patch anchor was not found in {patch.path}.")
    updated = original.replace(patch.old_text, patch.new_text, 1)
    path.write_text(updated, encoding="utf-8")


class CandidateWorkspace:
    def __init__(self, source_root: Path, approved_files: Sequence[Path]):
        self.source_root = source_root
        self.approved_files = tuple(approved_files)

    def _copy_source_tree(self, destination_root: Path) -> None:
        for source_path in self.approved_files:
            if not source_path.exists():
                continue
            relative_path = source_path.relative_to(self.source_root)
            destination_path = destination_root / relative_path
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination_path)

    @contextmanager
    def materialize(self, candidate: CandidateChange | None = None) -> Iterator[Path]:
        with tempfile.TemporaryDirectory(prefix="autoresearch-") as tmp_dir:
            workspace_root = Path(tmp_dir) / self.source_root.name
            workspace_root.mkdir(parents=True, exist_ok=True)
            self._copy_source_tree(workspace_root)
            if candidate is not None:
                for patch in candidate.patches:
                    apply_file_patch(workspace_root, patch)
            yield workspace_root
