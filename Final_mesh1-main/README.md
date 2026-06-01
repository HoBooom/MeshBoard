# CHESCA vs Mesh

이 폴더는 내려받은 공식 `CHESCA-main`을 수정하지 않고, 같은 CityLearn 2023
schema에서 다음 두 컨트롤러를 비교하기 위한 Colab 실행 프로젝트입니다.

- `chesca_official`: `CHESCA-main/agents/user_agent.py`의 `SubmissionAgent`를
  그대로 실행합니다. 공식 pretrained XGBoost, PID cooling, DHW 규칙,
  battery tree-search를 모두 그대로 사용합니다.
- `chesca_mesh`: 공식 CHESCA가 산출한 action을 각 건물 peer의 기본 선택지로
  유지하고, 배터리 유연성 메시지를 주고받아 district 부하 압력에 맞춰 추가
  협상합니다. HVAC, DHW, outage 처리, forecast 모델은 공식 구현을 유지합니다.

## 중요한 확인 결과

공식 코드의 `refine_actions_with_battery_controller()`는 각 건물의 전력 이력을
기준으로 배터리 tree-search를 개별 실행합니다. 즉, 현재 저장소의 CHESCA
소스에는 건물 간 중앙 community optimization 코드가 별도로 들어 있지
않습니다. 따라서 여기서의 mesh는 임의의 CHESCA 유사 기준선이 아니라,
공식 CHESCA 결과에 분산 협상층을 추가하는 실험입니다.

## Colab 실행

1. `chesca_vs_mesh` 폴더 전체를 Google Drive의 `MyDrive` 바로 아래에
   업로드합니다.
2. Colab에서 `RUN_CHESCA_VS_MESH_COLAB.ipynb`를 엽니다.
3. 설치 셀부터 순서대로 실행합니다.
4. 기본 실행은 `citylearn_challenge_2023_phase_3_1` 전체 기간에서 공식
   CHESCA와 mesh를 비교합니다.

공식 평가 환경인 `CityLearn==2.1b12`의 실행 모듈은
`third_party/CityLearn-2.1b12`에 포함되어 있습니다. PyPI의 해당 옛 배포본은
현재 pip 설치 과정에서 누락된 `requirements.txt` 때문에 실패할 수 있고,
오래된 scientific package pinning은 Colab에서 binary incompatibility를
일으킬 수 있습니다. 따라서 설치 셀은 CityLearn을 다시 설치하지 않고 필요한
dependency만 추가한 뒤 vendored 공식 모듈을 import합니다.

## 결과 파일

실행 결과는 다음 경로 아래 저장됩니다.

```text
results/<dataset>/<tag>/
  summary.csv
  citylearn_challenge_metrics.csv
  mesh_messages.csv
  mesh_negotiations.csv
  run_metadata.json
```

`summary.csv`의 변화율은 공식 CHESCA 대비 변화입니다. CityLearn 지표는
대체로 낮을수록 좋으므로 음수 변화율이 개선입니다.

단일 schema 실행의 `challenge_cost`는 논문의 leaderboard 목적함수입니다.
추가 notebook 셀은 public/private 평가 schema 세 개씩을 실행해 다음
파일도 저장합니다.

```text
results/paper_public_private_cost/
  public_private_runs.csv
  public_private_summary.csv
  paper_table.csv
  public_private_metadata.json
```

논문식 cost는 다음과 같이 계산됩니다.

```text
challenge_cost = 0.30 * comfort_cost
               + 0.10 * emissions_cost
               + 0.30 * grid_cost
               + 0.30 * resilience_cost
```

`grid_cost`는 ramping, daily load-factor penalty, daily peak, all-time
peak(공식 `2.1b12` key: `annual_peak_average`)의 평균이고,
`resilience_cost`는 thermal resilience penalty와 outage unserved energy의 평균입니다. `public_private_summary.csv`의
`leaderboard_cost`가 논문 표의 `Public Cost` 또는 `Private Cost`에
대응하는 비교 지표입니다. `paper_table.csv`는 두 cost를 논문처럼 같은 행에
배치하고 공식 CHESCA 대비 변화율을 함께 표시합니다.

## 구조

```text
CHESCA-main/                         # 다운로드한 공식 원본, 수정 없음
third_party/CityLearn-2.1b12/       # 공식 challenge 평가 런타임 소스
src/chesca_vs_mesh/official.py      # 공식 원본 import 및 schema 경로
src/chesca_vs_mesh/evaluation.py    # 동일 환경 비교 및 결과 저장
src/chesca_vs_mesh/mesh_agent.py    # CHESCA 기반 peer mesh
src/chesca_vs_mesh/protocol.py      # offer/broadcast/outcome 메시지 정의
Papers/CHESCA_IMPLEMENTATION.md     # 공식 코드와 mesh 경계 정리
RUN_CHESCA_VS_MESH_COLAB.ipynb     # Colab 단일 실행 notebook
```

## 해석 주의

`chesca_official`은 공식 코드 재현 경로이고, `chesca_mesh`는 새로운 가설입니다.
mesh가 성능을 개선하는지는 전체 기간 및 여러 phase에서 결과로 검증해야
합니다. 협상 메시지 수만 증가하고 공식 CHESCA 지표가 악화된다면, 분산
신호나 flex offer 설계를 수정해야 하는 근거가 됩니다.
