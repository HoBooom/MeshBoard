# MeshBoard Portfolio Guide

## 한 줄 소개

MeshBoard는 조직의 여러 AI 에이전트를 등록·배치하고, 이벤트를 적절한 에이전트에 라우팅하며, 정책과 실행 이력을 운영자가 통제할 수 있게 만든 Agent Mesh 운영 플랫폼입니다.

## 해결하려던 문제

단일 챗봇 데모는 에이전트가 늘어날수록 다음 질문에 답하기 어렵습니다.

- 어떤 에이전트가 어떤 요청을 받아야 하는가?
- 실행 가능한 도구와 민감정보 정책을 누가 강제하는가?
- 여러 에이전트의 위임과 실패를 어떻게 추적하는가?
- 운영 반영 전 시나리오를 안전하게 어떻게 검증하는가?

MeshBoard는 이 문제를 Registry, Workspace, Message Broker, Trust, Operations, Sandbox라는 명확한 경계로 나눴습니다.

## 대표 사용자 흐름

1. Creator가 에이전트 메타데이터, 역할, 구독 규칙과 허용 도구를 등록합니다.
2. Workspace에 필요한 에이전트를 배치하고 사용자/에이전트 간 subscription edge를 구성합니다.
3. 메시지는 `@mention`, 명시적 ID/role, subscription 순으로 라우팅됩니다.
4. 활성 정책을 통과한 에이전트만 LangGraph 런타임과 도구를 실행합니다.
5. 운영자는 `ltree` 실행 트리에서 요청·위임·추론·도구·실패를 확인합니다.
6. 배포 전에는 Sandbox에서 같은 라우팅 결정을 운영 데이터 쓰기 없이 재현합니다.

## 핵심 기술적 판단

| 판단 | 구현 | 이유 |
|---|---|---|
| 프롬프트가 아닌 실행 경계에서 도구 제한 | agent allow-list와 policy allow/deny 교집합 | 모델 지시 위반이 실제 도구 실행으로 이어지지 않게 함 |
| 결정론적 Sandbox 분리 | `sandbox_runs` 전용 기록과 `production_write_count = 0` 제약 | 운영 메시지·Interaction 오염 없이 라우팅 검증 |
| 계층 실행 추적 | `execution_tree_id` + PostgreSQL `ltree` | A2A 위임 경로를 정렬 가능한 단일 트리로 조회 |
| 불변 감사 보관 | 트랜잭션 이관 + UPDATE/DELETE 거부 trigger | 애플리케이션 실수로 감사 기록이 바뀌는 것을 DB에서 차단 |
| 호환성 우선 조회 | interaction v1→v2 read adapter | 과거 데이터를 일괄 재작성하지 않고 새 UI 계약 유지 |
| 안전한 외부 연동 | HMAC-SHA256 웹훅, production HTTPS | SIEM 수신 측에서 출처와 본문 무결성 검증 가능 |

## 5분 데모 순서

1. `SEED_DB=1 RUN_APP=1 ./init.sh`로 데모 데이터를 준비합니다.
2. Creator Workbench에서 에이전트의 도구와 구독 규칙을 확인합니다.
3. Sandbox에서 직접 멘션 시나리오를 실행하고 의사결정 로그와 운영 쓰기 0건을 보여줍니다.
4. Trust Workbench에서 유효/무효 정책 템플릿 검증과 인증 배지를 보여줍니다.
5. Workspace에서 에이전트에게 메시지를 보내 receipt와 응답을 생성합니다.
6. Operations에서 실행 트리, 실패 원인, 모델 통계, archive dry-run과 웹훅 상태를 확인합니다.

## 검증 근거

- Backend 단위/서비스 테스트 58개
- Frontend TypeScript build 및 ESLint 무경고
- PostgreSQL Alembic `015_member_role` head
- 실제 API E2E: Sandbox 운영 Interaction 수 불변, 정책 위반 403, 런타임 Suspend/Activate 복원, 실행 트리 조회
- CI: pull request 및 `main` push에서 backend/frontend 품질 게이트 실행

## 운영 확장 경계

이 저장소는 포트폴리오 MVP의 완결성을 목표로 합니다. 다음은 의도적으로 완료 범위에서 제외했습니다.

- 프로세스 재시작을 견디는 LangGraph checkpointer
- Kafka/SQS 같은 durable worker queue와 재시도/Dead Letter Queue
- SSE/WebSocket 기반 실시간 스트리밍
- 실제 기업 OIDC provider 및 secret manager 연동
- 대규모 분석용 materialized view와 장기 부하 테스트

이 경계를 README와 API 응답(`durable=false`)에 명시해 데모 기능을 운영 수준으로 과장하지 않았습니다.
