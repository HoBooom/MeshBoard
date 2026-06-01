"""Client for the out-of-process CHESCA (mesh_chesca) worker.

Keeps a single long-lived worker subprocess (see mesh_chesca_worker.py) and talks to it
with line-delimited JSON. This isolates the vendored CityLearn 2.1b12 (used by CHESCA)
from the main API process's CityLearn_old_system (used by SACRBC) so the two cannot
shadow each other's ``citylearn`` package.

The worker holds the incremental rollout cache, so repeated board requests for the same
(dataset, scenario) stay fast across calls.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional


BACKEND_DIR = Path(__file__).resolve().parents[2]  # services -> app -> backend


class MeshChescaWorkerError(RuntimeError):
    """Raised when the worker reports a failure or the channel breaks."""


class _WorkerClient:
    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.RLock()
        self._req_id = 0

    def _ensure_proc(self) -> subprocess.Popen:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        # (re)spawn the worker in the same venv python.
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "app.services.mesh_chesca_worker"],
            cwd=str(BACKEND_DIR),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        return self._proc

    def _request(self, op: str, args: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            proc = self._ensure_proc()
            self._req_id += 1
            req_id = self._req_id
            assert proc.stdin is not None and proc.stdout is not None
            try:
                proc.stdin.write(json.dumps({"id": req_id, "op": op, "args": args}) + "\n")
                proc.stdin.flush()
            except (BrokenPipeError, ValueError) as exc:
                self._kill()
                raise MeshChescaWorkerError(f"worker write failed: {exc}") from exc

            # 워커는 요청당 정확히 한 줄 JSON 응답을 보낸다.
            while True:
                line = proc.stdout.readline()
                if line == "":
                    self._kill()
                    raise MeshChescaWorkerError("worker exited unexpectedly")
                line = line.strip()
                if not line:
                    continue
                try:
                    resp = json.loads(line)
                except json.JSONDecodeError:
                    continue  # 혹시 섞인 비프로토콜 출력은 무시
                if resp.get("id") != req_id:
                    continue
                if resp.get("ok"):
                    return resp.get("result") or {}
                raise MeshChescaWorkerError(str(resp.get("error") or "worker error"))

    def _kill(self) -> None:
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:  # noqa: BLE001
                pass
            self._proc = None

    # ── public ops ──────────────────────────────────────────────────

    def board_snapshot(self, *, step: int, scenario: str, dataset: str, window: int) -> Dict[str, Any]:
        return self._request(
            "board",
            {"step": step, "scenario": scenario, "dataset": dataset, "window": window},
        )

    def status(self, *, scenario: str, dataset: str, connect: bool) -> Dict[str, Any]:
        return self._request(
            "status",
            {"scenario": scenario, "dataset": dataset, "connect": connect},
        )


_client = _WorkerClient()


def board_snapshot(*, step: int, scenario: str, dataset: str, window: int) -> Dict[str, Any]:
    return _client.board_snapshot(step=step, scenario=scenario, dataset=dataset, window=window)


def status(*, scenario: str, dataset: str, connect: bool) -> Dict[str, Any]:
    return _client.status(scenario=scenario, dataset=dataset, connect=connect)
