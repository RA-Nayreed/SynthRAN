"""Atomic ID allocation and rebuildable workspace index."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from pathlib import Path
import sqlite3

from synthran.workspace.model import (
    ExperimentRecord,
    ExperimentStatus,
    WorkspaceError,
    format_utc,
    utc_now,
    validate_experiment_id,
    validate_operation_id,
    validate_run_id,
)
from synthran.workspace.store import (
    experiment_directory,
    load_experiment_record,
    save_experiment_record,
    set_active_experiment,
    workspace_directory,
)


REGISTRY_SCHEMA = 1
RUN_LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")


@dataclass(frozen=True)
class ExperimentEntry:
    experiment_id: str
    created_at_utc: str
    status: str
    path: str


class WorkspaceRegistry:
    """SQLite index whose research records remain recoverable from experiment folders."""

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()
        self.path = workspace_directory(self.workspace_root) / "registry.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS counters (
                    key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL CHECK(value >= 0)
                );
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    created_at_utc TEXT NOT NULL,
                    status TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS runs (
                    experiment_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    label TEXT,
                    created_at_utc TEXT NOT NULL,
                    PRIMARY KEY (experiment_id, run_id),
                    UNIQUE (experiment_id, ordinal),
                    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
                );
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY,
                    ordinal INTEGER NOT NULL UNIQUE CHECK(ordinal > 0),
                    experiment_id TEXT,
                    kind TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
                );
                """
            )
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema'"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO metadata(key, value) VALUES('schema', ?)",
                    (str(REGISTRY_SCHEMA),),
                )
            elif row[0] != str(REGISTRY_SCHEMA):
                raise WorkspaceError("workspace registry schema is unsupported")

    @staticmethod
    def _next_counter(connection: sqlite3.Connection, key: str) -> int:
        row = connection.execute(
            "SELECT value FROM counters WHERE key = ?", (key,)
        ).fetchone()
        value = (int(row[0]) if row else 0) + 1
        connection.execute(
            "INSERT INTO counters(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        return value

    def issue_experiment_id(self, now: datetime | None = None) -> str:
        current = (now or utc_now()).astimezone(timezone.utc)
        date_stamp = current.strftime("%Y%m%d")
        created = format_utc(current)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            ordinal = self._next_counter(connection, f"experiment:{date_stamp}")
            experiment_id = f"sran-{date_stamp}-{ordinal:03d}"
            validate_experiment_id(experiment_id)
            relative = f"experiments/{experiment_id}"
            connection.execute(
                "INSERT INTO experiments(experiment_id, created_at_utc, status, path) "
                "VALUES(?, ?, 'issued', ?)",
                (experiment_id, created, relative),
            )
            connection.execute("COMMIT")
        directory = experiment_directory(self.workspace_root, experiment_id)
        try:
            directory.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            self.mark_experiment_status(experiment_id, "failed")
            raise WorkspaceError(
                f"issued experiment directory already exists for {experiment_id}; ID remains consumed"
            ) from exc
        except OSError as exc:
            self.mark_experiment_status(experiment_id, "failed")
            raise WorkspaceError(
                f"unable to create experiment directory for {experiment_id}; ID remains consumed in the registry"
            ) from exc
        return experiment_id

    def create_experiment(
        self,
        *,
        profile: str,
        project: str,
        label: str | None = None,
        slices_experiment: str | None = None,
        network_intent: str = "unspecified",
        radio_mode: str = "automatic",
        now: datetime | None = None,
        activate: bool = True,
    ) -> ExperimentRecord:
        current = (now or utc_now()).astimezone(timezone.utc)
        experiment_id = self.issue_experiment_id(current)
        record = ExperimentRecord(
            experiment_id=experiment_id,
            created_at_utc=format_utc(current),
            profile=profile,
            project=project,
            label=label,
            slices_experiment=slices_experiment,
            network_intent=network_intent,
            radio_mode=radio_mode,
        )
        directory = experiment_directory(self.workspace_root, experiment_id)
        try:
            for name in ("providers", "operations", "runs", "evidence", "datasets"):
                (directory / name).mkdir(exist_ok=False)
            save_experiment_record(self.workspace_root, record)
            self._write_status(
                ExperimentStatus(
                    experiment_id=experiment_id,
                    state="configured",
                    updated_at_utc=format_utc(current),
                )
            )
            self.mark_experiment_status(experiment_id, "configured")
            if activate:
                set_active_experiment(self.workspace_root, experiment_id)
        except Exception as exc:
            self.mark_experiment_status(experiment_id, "failed")
            try:
                self._write_status(
                    ExperimentStatus(
                        experiment_id=experiment_id,
                        state="failed",
                        updated_at_utc=format_utc(utc_now()),
                        notes=("experiment initialization did not complete",),
                    )
                )
            except Exception:
                pass
            if isinstance(exc, WorkspaceError):
                raise
            raise WorkspaceError(
                f"experiment {experiment_id} could not be initialized; its ID remains consumed"
            ) from exc
        return record

    def _write_status(self, status: ExperimentStatus) -> Path:
        import json
        import os
        import tempfile

        directory = experiment_directory(self.workspace_root, status.experiment_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "status.json"
        content = json.dumps(status.to_dict(), indent=2, sort_keys=True) + "\n"
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=directory,
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        os.chmod(temporary_path, 0o600)
        temporary_path.replace(path)
        return path

    def mark_experiment_status(self, experiment_id: str, status: str) -> None:
        validate_experiment_id(experiment_id)
        if status not in {"issued", "configured", "active", "expired", "closed", "failed"}:
            raise WorkspaceError("registry experiment status is unsupported")
        with self._connect() as connection:
            updated = connection.execute(
                "UPDATE experiments SET status = ? WHERE experiment_id = ?",
                (status, experiment_id),
            ).rowcount
        if updated != 1:
            raise WorkspaceError(f"experiment {experiment_id} is not indexed")

    def list_experiments(self) -> tuple[ExperimentEntry, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT experiment_id, created_at_utc, status, path "
                "FROM experiments ORDER BY created_at_utc, experiment_id"
            ).fetchall()
        return tuple(ExperimentEntry(*map(str, row)) for row in rows)

    def issue_run_id(
        self,
        *,
        experiment_id: str,
        label: str | None = None,
        now: datetime | None = None,
    ) -> str:
        validate_experiment_id(experiment_id)
        if label is not None and not RUN_LABEL_RE.fullmatch(label):
            raise WorkspaceError(
                "run label must start with a lowercase letter or number and contain only lowercase letters, numbers, or '-'"
            )
        created = format_utc(now or utc_now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute(
                "SELECT 1 FROM experiments WHERE experiment_id = ?", (experiment_id,)
            ).fetchone()
            if exists is None:
                connection.execute("ROLLBACK")
                raise WorkspaceError(f"experiment {experiment_id} is not indexed")
            ordinal = self._next_counter(connection, f"run:{experiment_id}")
            run_id = f"run-{ordinal:03d}" + (f"-{label}" if label else "")
            validate_run_id(run_id)
            connection.execute(
                "INSERT INTO runs(experiment_id, run_id, ordinal, label, created_at_utc) "
                "VALUES(?, ?, ?, ?, ?)",
                (experiment_id, run_id, ordinal, label, created),
            )
            connection.execute("COMMIT")
        run_directory = experiment_directory(self.workspace_root, experiment_id) / "runs" / run_id
        try:
            run_directory.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            raise WorkspaceError(
                f"unable to create run directory for {run_id}; ID remains consumed"
            ) from exc
        return run_id

    def issue_operation_id(
        self,
        *,
        kind: str,
        experiment_id: str | None = None,
        now: datetime | None = None,
    ) -> str:
        if not kind or len(kind) > 64 or any(
            not (character.isalnum() or character in "._-") for character in kind
        ):
            raise WorkspaceError("operation kind contains unsafe characters")
        if experiment_id is not None:
            validate_experiment_id(experiment_id)
        created = format_utc(now or utc_now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if experiment_id is not None:
                exists = connection.execute(
                    "SELECT 1 FROM experiments WHERE experiment_id = ?", (experiment_id,)
                ).fetchone()
                if exists is None:
                    connection.execute("ROLLBACK")
                    raise WorkspaceError(f"experiment {experiment_id} is not indexed")
            ordinal = self._next_counter(connection, "operation")
            operation_id = f"op-{ordinal:06d}"
            validate_operation_id(operation_id)
            connection.execute(
                "INSERT INTO operations(operation_id, ordinal, experiment_id, kind, created_at_utc) "
                "VALUES(?, ?, ?, ?, ?)",
                (operation_id, ordinal, experiment_id, kind, created),
            )
            connection.execute("COMMIT")
        directory = workspace_directory(self.workspace_root) / "operations" / operation_id
        try:
            directory.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            raise WorkspaceError(
                f"unable to create operation directory for {operation_id}; ID remains consumed"
            ) from exc
        return operation_id

    def rebuild_from_experiment_folders(self) -> int:
        """Rebuild the experiment index and daily counters from durable folders."""

        experiment_root = workspace_directory(self.workspace_root) / "experiments"
        experiment_root.mkdir(parents=True, exist_ok=True)
        records: list[ExperimentRecord] = []
        consumed: list[tuple[str, str]] = []
        for directory in sorted(path for path in experiment_root.iterdir() if path.is_dir()):
            try:
                validate_experiment_id(directory.name)
            except WorkspaceError:
                continue
            record_path = directory / "experiment.toml"
            if record_path.is_file():
                records.append(load_experiment_record(self.workspace_root, directory.name))
                consumed.append((directory.name, "configured"))
            else:
                consumed.append((directory.name, "failed"))

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM runs")
            connection.execute("DELETE FROM operations")
            connection.execute("DELETE FROM experiments")
            connection.execute("DELETE FROM counters")
            record_map = {record.experiment_id: record for record in records}
            for experiment_id, status in consumed:
                date_stamp, ordinal_text = experiment_id.split("-")[1:]
                ordinal = int(ordinal_text)
                counter_key = f"experiment:{date_stamp}"
                current = connection.execute(
                    "SELECT value FROM counters WHERE key = ?", (counter_key,)
                ).fetchone()
                if current is None or int(current[0]) < ordinal:
                    connection.execute(
                        "INSERT INTO counters(key, value) VALUES(?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (counter_key, ordinal),
                    )
                record = record_map.get(experiment_id)
                created_at = (
                    record.created_at_utc
                    if record is not None
                    else f"{date_stamp[0:4]}-{date_stamp[4:6]}-{date_stamp[6:8]}T00:00:00Z"
                )
                connection.execute(
                    "INSERT INTO experiments(experiment_id, created_at_utc, status, path) "
                    "VALUES(?, ?, ?, ?)",
                    (
                        experiment_id,
                        created_at,
                        status,
                        f"experiments/{experiment_id}",
                    ),
                )
            connection.execute("COMMIT")
        return len(consumed)
