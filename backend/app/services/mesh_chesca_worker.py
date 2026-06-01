"""Out-of-process worker for the CHESCA (mesh_chesca) runtime.

WHY A SUBPROCESS: the mesh_chesca runtime imports the vendored CityLearn 2.1b12, which
registers the top-level package name ``citylearn`` — the SAME name used by the SACRBC
runtime's ``CityLearn_old_system``. Python caches a package by name in ``sys.modules``,
so loading 2.1b12 in the main API process permanently shadows the old CityLearn and
breaks SACRBC inference (KeyError 'kg_CO2/kWh'). Running CHESCA in its own process keeps
the two CityLearn versions fully isolated.

PROTOCOL: line-delimited JSON over stdin/stdout.
  request  : {"id": <int>, "op": "board"|"status", "args": {...}}
  response : {"id": <int>, "ok": true, "result": {...}} | {"id": <int>, "ok": false, "error": "..."}

Library chatter (gym/xgboost/citylearn prints) is redirected away from the protocol fd so
it cannot corrupt the JSON stream.
"""

from __future__ import annotations

import json
import os
import sys

# OMP를 단일 스레드로: xgboost(OpenMP)가 numpy 등 다른 OMP 런타임과 충돌해 SIGSEGV 나는 것 회피.
# 반드시 runtime(=citylearn/xgboost) import 이전에 설정.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")


def _main() -> None:
    # 실제 stdout(fd 1)은 프로토콜 전용으로 보존하고, 라이브러리 출력은 stderr로 보낸다.
    protocol_fd = os.dup(1)
    os.dup2(2, 1)  # 이후 print()/라이브러리 stdout → stderr
    protocol = os.fdopen(protocol_fd, "w", buffering=1)

    def respond(obj: dict) -> None:
        protocol.write(json.dumps(obj, ensure_ascii=False) + "\n")
        protocol.flush()

    # lazy import: 첫 요청 처리 시점에 citylearn 2.1b12 + checa 적재.
    from app.services.mesh_chesca_runtime import (  # noqa: E402
        get_mesh_chesca_board_snapshot,
        runtime_status,
    )

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        req_id = req.get("id")
        op = req.get("op")
        args = req.get("args") or {}
        try:
            if op == "board":
                result = get_mesh_chesca_board_snapshot(**args)
            elif op == "status":
                result = runtime_status(**args)
            else:
                raise ValueError(f"unknown op '{op}'")
            respond({"id": req_id, "ok": True, "result": result})
        except Exception as exc:  # noqa: BLE001 - relay any failure to the client
            respond({"id": req_id, "ok": False, "error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    _main()
