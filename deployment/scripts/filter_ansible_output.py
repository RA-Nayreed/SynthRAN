#!/usr/bin/env python3
"""Render Ansible plays, nested roles, tasks and host results as a live hierarchy."""

from __future__ import annotations

import json
import re
import sys

HEADING = re.compile(r"^(TASK|RUNNING HANDLER|PLAY) \[(.*?)](?:\s+\*+)?$")
RESULT = re.compile(r"^(ok|changed|skipping|fatal): \[([^]]+)](.*)$")
ANSI = re.compile(r"\x1b\[[0-9;]*m")
NAMES = {
    "5g": "5G",
    "r2lab": "R2Lab",
    "k8s": "Kubernetes",
    "oai": "OAI",
    "srsRAN": "srsRAN",
}


def label(part: str) -> str:
    return NAMES.get(part, part.replace("_", " ").replace("-", " "))


class Progress:
    def __init__(self, output):
        self.output = output
        self.play = None
        self.task = None
        self.role = ()
        self.depth = 1
        self.hide_detail = False
        self.diagnostic = []
        self.waiting = set()
        self.pending_failure = None

    def emit(self, text="", depth=0):
        print("  " * depth + text, file=self.output, flush=True)

    def heading(self):
        if self.play is not None:
            self.emit()
            self.emit(self.play)
            self.play = None
            self.role = ()
        if self.task is None:
            return
        role, separator, task = self.task.partition(" : ")
        parts = tuple(role.split("/")) if separator else ()
        shared = 0
        while (
            shared < min(len(parts), len(self.role))
            and parts[shared] == self.role[shared]
        ):
            shared += 1
        for index in range(shared, len(parts)):
            self.emit(label(parts[index]), index + 1)
        self.role = parts
        self.depth = len(parts) + 1
        self.emit(task if separator else role, self.depth)
        self.task = None

    def flush_diagnostic(self):
        if self.diagnostic:
            self.heading()
            for line in self.diagnostic:
                self.emit(line, self.depth + 1)
            self.diagnostic.clear()

    @staticmethod
    def failure_message(detail: str) -> str:
        try:
            value = json.loads(detail.partition("=>")[2])
            message = "\n".join(
                str(value[key]) for key in ("msg", "stderr") if value.get(key)
            )
            if not message:
                message = str(value.get("stdout", detail))
            return message
        except (ValueError, TypeError):
            return detail.strip()

    def flush_failure(self, ignored=False):
        if self.pending_failure is None:
            return
        host, detail = self.pending_failure
        self.pending_failure = None
        self.flush_diagnostic()
        self.heading()
        if ignored:
            status = "IGNORED FAILURE (non-fatal)"
        else:
            status = "UNREACHABLE" if "UNREACHABLE!" in detail else "FAILED"
        self.emit(f"{host}: {status}", self.depth + 1)
        for text in self.failure_message(detail).splitlines():
            self.emit(text, self.depth + 2)
        self.hide_detail = True

    def feed(self, raw):
        line = ANSI.sub("", raw.rstrip("\r\n"))

        # Ansible prints an ignored task as a fatal-looking result followed by
        # a separate "...ignoring" line. Delay rendering by one line so an
        # intentionally ignored probe is never presented as a fatal failure.
        if self.pending_failure is not None:
            if line.strip() == "...ignoring":
                self.flush_failure(ignored=True)
                return
            self.flush_failure(ignored=False)

        match = HEADING.match(line)
        if match:
            self.flush_diagnostic()
            self.hide_detail = False
            self.waiting.clear()
            if match[1] == "PLAY":
                self.play = match[2]
                self.task = None
            else:
                self.task = match[2]
            return
        if line.startswith("[ERROR]"):
            self.flush_diagnostic()
            self.diagnostic = [line]
            return
        match = RESULT.match(line)
        if match:
            status, host, detail = match.groups()
            if status == "fatal":
                self.pending_failure = (host, detail)
                return
            if status != "skipping":
                # failed_when:false can produce [ERROR] followed by a successful
                # result. The actual task result is authoritative in that case.
                self.diagnostic.clear()
                self.heading()
                self.emit(f"{host}: {status}", self.depth + 1)
            else:
                self.diagnostic.clear()
            self.hide_detail = True
            return
        if line.startswith("FAILED - RETRYING:"):
            self.diagnostic.clear()
            self.heading()
            host = line.partition("[")[2].partition("]")[0] or "task"
            if host not in self.waiting:
                self.emit(f"{host}: waiting", self.depth + 1)
                self.waiting.add(host)
            return
        if line.startswith("skipping: no hosts matched"):
            self.play = self.task = None
            return
        if line.startswith("included:"):
            self.diagnostic.clear()
            self.hide_detail = True
            return
        if line.startswith("PLAY RECAP"):
            self.flush_diagnostic()
            self.play = self.task = None
            self.hide_detail = False
            self.emit("\nRun summary")
            return
        if line.startswith(
            ("NO MORE HOSTS LEFT", "[WARNING]", "[DEPRECATION WARNING]")
        ):
            self.flush_diagnostic()
            self.heading()
            self.hide_detail = False
            self.emit(line, self.depth + 1)
            return
        if self.diagnostic:
            self.diagnostic.append(line)
        elif line.strip() and not self.hide_detail:
            self.emit(line)

    def finish(self):
        # Syntax/inventory errors may terminate Ansible without a fatal result.
        self.flush_failure(ignored=False)
        self.flush_diagnostic()


def main():
    progress = Progress(sys.stdout)
    for line in sys.stdin:
        progress.feed(line)
    progress.finish()


if __name__ == "__main__":
    main()
