# research/ — MACRO-Mesh v2 완전 독립 실험

처음 보는 연구자가 **macro_mesh_v2의 구조·로직을 단독으로 실험·검증**하기 위한 공간이다.
보드 UI 없이 터미널 출력만으로 동작과 결과를 확인한다.

## 노트북: `macro_mesh_v2_standalone.ipynb`
- **데이터 CSV(선택) 1개 + 이 ipynb 1개면 전부 실행된다.** 프로젝트의 다른 `.py`
  (app.services, eval_modes, vendored CityLearn 등)를 **import하지 않는다** —
  미니 단지 시뮬레이터·에이전트·v2의 3모듈(CoProposer rollout / Negotiator / Introspector)을
  모두 노트북 셀 안에 인라인 재구현했다.
- 상단(§1~§8)에 문제 정의, 에이전트·도구 구조, 의사결정 파이프라인, 산식, 매개변수, 지표를
  전문가 수준으로 정리. 이어서 셀을 위에서부터 실행.

## 실행 방법
```bash
pip install numpy pandas          # 기본
pip install openai                # USE_LLM=True 로 실제 LLM 협상/복기를 볼 때만
jupyter lab research/macro_mesh_v2_standalone.ipynb
```
> 백엔드/DB/CityLearn 설치 불필요. 일반 Python 커널이면 된다.

## 데이터 CSV
셀 1의 `DATA_CSV`에:
- `None` → **합성 데이터**(일주기+정오 PV+노이즈, 시드 고정)로 항상 실행.
- CityLearn 스타일 CSV(`non_shiftable_load`,`solar_generation` 컬럼) → 1-building 템플릿으로 N개 복제.
- 숫자 컬럼이 여러 개인 CSV → 각 컬럼 = building별 부하 시계열.

## 권장 순서
1. `USE_LLM=False`(기본) → 무료·즉시 실행, 파이프라인·rollout·introspector(heuristic) 동작 확인.
2. `USE_LLM=True` + `RUNYOUR_API_KEY` 설정 → 실제 Sonnet으로 building 협상 + Introspector 복기.
3. `N_BUILDINGS`(확장성), `INITIAL_SOC`, `MAX_ROUNDS`, `DATA_CSV`를 바꿔가며 비교.

## 운영 코드와의 관계
이 노트북은 v2 **로직을 충실히 재현한 경량 standalone 버전**이다. 실제 운영 구현은
LangGraph 런타임 + 실제 CityLearn env를 사용한다:
- 운영 v2 서비스: [`../backend/app/services/citylearn_macro_mesh_v2.py`](../backend/app/services/citylearn_macro_mesh_v2.py)
- 보드 통합/실험 결과 보고서: [`../docs/CityLearn_MacroMesh_v2_Experiment.md`](../docs/CityLearn_MacroMesh_v2_Experiment.md)
