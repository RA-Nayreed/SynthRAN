"""Deterministic packaging for a reviewed physical srsRAN Helm chart.

The chart is packaged only after the guarded overlay and offline Helm render have
been validated.  Packaging is local and deterministic: file order and tar
metadata are normalized, symbolic links are rejected, and gzip time metadata is
fixed.  The resulting digest can be bound to later live evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import hashlib
from pathlib import Path
import tarfile

from synthran.network.r2lab_physical_chart_workspace import (
    VALUES_FILE_NAME,
    PhysicalChartWorkspace,
)
from synthran.network.runtime import validate_run_id


class R2LabPhysicalArtifactError(RuntimeError):
    """Raised when a deterministic physical chart artifact cannot be produced."""


@dataclass(frozen=True)
class PhysicalChartArtifact:
    run_id: str
    package_path: Path
    package_sha256: str
    values_sha256: str

    def to_dict(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "package_file": self.package_path.name,
            "package_sha256": self.package_sha256,
            "values_file": VALUES_FILE_NAME,
            "values_sha256": self.values_sha256,
            "acceptance": "offline-packaged-only",
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise R2LabPhysicalArtifactError("unable to hash physical chart artifact") from exc
    return digest.hexdigest()


def package_physical_chart(
    *,
    workspace: PhysicalChartWorkspace,
    run_id: str,
    destination: Path,
) -> PhysicalChartArtifact:
    """Create one deterministic ``.tgz`` from the isolated reviewed chart tree."""

    try:
        validated_run_id = validate_run_id(run_id)
    except Exception as exc:
        raise R2LabPhysicalArtifactError(str(exc)) from exc
    chart_root = workspace.chart_root
    if not chart_root.is_dir() or not workspace.values_file.is_file():
        raise R2LabPhysicalArtifactError("physical chart workspace is incomplete")

    try:
        files = sorted(
            path
            for path in chart_root.rglob("*")
            if path.is_file() or path.is_symlink()
        )
    except OSError as exc:
        raise R2LabPhysicalArtifactError("unable to enumerate physical chart workspace") from exc
    if not files:
        raise R2LabPhysicalArtifactError("physical chart workspace contains no files")
    if any(path.is_symlink() for path in files):
        raise R2LabPhysicalArtifactError("physical chart workspace must not contain symbolic links")

    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    package_path = destination / f"srsran-gnb-{validated_run_id}.tgz"
    if package_path.exists():
        raise R2LabPhysicalArtifactError("physical chart package already exists")

    try:
        with package_path.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                    for path in files:
                        relative = path.relative_to(chart_root)
                        arcname = Path("srsran-gnb") / relative
                        info = archive.gettarinfo(str(path), arcname=arcname.as_posix())
                        info.uid = 0
                        info.gid = 0
                        info.uname = ""
                        info.gname = ""
                        info.mtime = 0
                        info.mode = 0o644
                        with path.open("rb") as stream:
                            archive.addfile(info, stream)
    except OSError as exc:
        package_path.unlink(missing_ok=True)
        raise R2LabPhysicalArtifactError("unable to package physical chart workspace") from exc

    return PhysicalChartArtifact(
        run_id=validated_run_id,
        package_path=package_path,
        package_sha256=_sha256_file(package_path),
        values_sha256=workspace.values_sha256,
    )
