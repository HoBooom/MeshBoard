-- =============================================================================
-- Agent Mesh Platform — Full Registry Schema
-- Version: 2.0
-- Updated: 2026-03-21
--
-- 테이블 목록 (17개)
--   사용자/권한   : users, user_roles
--   에이전트/거버넌스: agents, agent_subscription_rules,
--                    policies, agent_policies,
--                    certifications, agent_certifications
--   워크스페이스  : workspaces, goals
--   대화/메시지   : conversations, messages
--   메시지 라우팅 : message_headers, message_receipts
--   상호작용      : interactions, interaction_archive
--   공지          : notices
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid()


-- ===========================================================================
-- SECTION 1. 사용자 / 권한
-- ===========================================================================

-- 1-1. users
CREATE TABLE users (
    user_id       UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    name          VARCHAR(255) NOT NULL,
    email         VARCHAR(255) UNIQUE NOT NULL,
    login_id      VARCHAR(50)  UNIQUE NOT NULL,
    password_hash TEXT         NOT NULL,
    -- OIDC 연동 (기업 IdP)
    idp_sub       VARCHAR(255),                    -- OIDC sub 클레임
    idp_iss       VARCHAR(255),                    -- OIDC issuer URL
    state         VARCHAR(20)  NOT NULL DEFAULT 'ACTIVE'
                      CHECK (state IN ('ACTIVE','INACTIVE','SUSPENDED')),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_login    TIMESTAMPTZ,
    UNIQUE (idp_sub, idp_iss)
);

COMMENT ON TABLE  users         IS '시스템 사용자';
COMMENT ON COLUMN users.idp_sub IS 'OIDC sub — IdP가 부여한 불변 사용자 식별자';
COMMENT ON COLUMN users.idp_iss IS 'OIDC iss — 토큰 발급 IdP URL (멀티 IdP 지원)';


-- 1-2. user_roles  (유저 : 역할 = 1 : N)
CREATE TABLE user_roles (
    user_id    UUID        NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    role       VARCHAR(50) NOT NULL
                   CHECK (role IN (
                       'agent_owner',      -- 에이전트 소유자
                       'agent_engineer',   -- 에이전트 엔지니어
                       'trust_ops',        -- 신뢰성 및 운영 전문가
                       'governance',       -- 거버넌스 및 인증 책임자
                       'evaluator',        -- 평가 및 인간 개입 감독관
                       'ethics_liaison',   -- 정책 및 윤리 연락 담당자
                       'release_manager'   -- 릴리스 관리자
                   )),
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by UUID        REFERENCES users(user_id),
    PRIMARY KEY (user_id, role)
);

COMMENT ON TABLE user_roles IS '사용자 역할 매핑 — 한 사용자가 여러 역할 보유 가능';


-- ===========================================================================
-- SECTION 2. 에이전트 / 거버넌스
-- ===========================================================================

-- 2-1. agents
CREATE TABLE agents (
    agent_id      UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    name          VARCHAR(255) UNIQUE NOT NULL,
    version       VARCHAR(50)  NOT NULL,
    purpose       TEXT,
    description   TEXT,
    approach      TEXT,                        -- 실행 방식 설명
    owner_id      UUID         NOT NULL REFERENCES users(user_id),
    status        VARCHAR(20)  NOT NULL DEFAULT 'DRAFT'
                      CHECK (status IN ('DRAFT','ACTIVE','DEPRECATED','SUSPENDED')),
    visibility    VARCHAR(20)  NOT NULL DEFAULT 'PRIVATE'
                      CHECK (visibility IN ('PUBLIC','DEPARTMENT','PRIVATE')),
    -- SAM Agent Card 원본 (JSON)
    agent_card    JSONB        NOT NULL DEFAULT '{}',
    -- 확장 메타데이터
    roles         JSONB        NOT NULL DEFAULT '[]',  -- ["analyst","manager"]
    collaborators JSONB        NOT NULL DEFAULT '[]',  -- 협업 에이전트 목록
    tools         JSONB        NOT NULL DEFAULT '[]',  -- 사용 도구 목록
    metadata      JSONB        NOT NULL DEFAULT '{}',  -- 자유 확장 필드
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE  agents            IS '에이전트 레지스트리 — SAM Agent Card 기반 확장';
COMMENT ON COLUMN agents.agent_card IS 'SAM YAML agent_card 섹션 원본 보관';
COMMENT ON COLUMN agents.visibility IS 'PUBLIC=전사 공개, DEPARTMENT=부서, PRIVATE=비공개';


-- 2-2. agent_subscription_rules  (Selective Consumption 수신 규칙)
CREATE TABLE agent_subscription_rules (
    rule_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id       UUID        NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    -- 수신 조건 (OR 조합 — 하나라도 매칭되면 수신)
    watch_domains  TEXT[]      NOT NULL DEFAULT '{}',  -- ["finance","hr"]
    watch_intents  TEXT[]      NOT NULL DEFAULT '{}',  -- ["data_request","alert"]
    watch_tags     TEXT[]      NOT NULL DEFAULT '{}',  -- ["KPI","quarterly"]
    watch_senders  UUID[]      NOT NULL DEFAULT '{}',  -- 특정 발신자 ID 구독
    watch_roles    TEXT[]      NOT NULL DEFAULT '{}',  -- 특정 역할의 발신자 구독
    -- 수신 거부 조건 (블랙리스트 — 우선 적용)
    ignore_senders UUID[]      NOT NULL DEFAULT '{}',
    ignore_tags    TEXT[]      NOT NULL DEFAULT '{}',
    -- 우선순위 필터
    min_priority   VARCHAR(10) NOT NULL DEFAULT 'low'
                       CHECK (min_priority IN ('low','medium','high','critical')),
    is_active      BOOLEAN     NOT NULL DEFAULT true,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  agent_subscription_rules             IS '에이전트별 메시지 수신 규칙 — Selective Consumption 패턴';
COMMENT ON COLUMN agent_subscription_rules.watch_domains IS '관심 도메인 목록 (OR 조건)';
COMMENT ON COLUMN agent_subscription_rules.ignore_senders IS '블랙리스트 — watch 조건보다 우선 적용';


-- 2-3. policies
CREATE TABLE policies (
    policy_id   UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(255) NOT NULL,
    purpose     TEXT,
    description TEXT,
    template    JSONB        NOT NULL DEFAULT '{}',  -- 정책 규칙 JSON
    status      VARCHAR(20)  NOT NULL DEFAULT 'DRAFT'
                    CHECK (status IN ('DRAFT','ACTIVE','REVOKED')),
    created_by  UUID         REFERENCES users(user_id),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE policies IS '에이전트에 적용되는 정책 정의 — 신뢰 워크벤치에서 관리';


-- 2-4. agent_policies  (에이전트 ↔ 정책 N:M)
CREATE TABLE agent_policies (
    agent_id   UUID        NOT NULL REFERENCES agents(agent_id)    ON DELETE CASCADE,
    policy_id  UUID        NOT NULL REFERENCES policies(policy_id) ON DELETE CASCADE,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied_by UUID        REFERENCES users(user_id),
    PRIMARY KEY (agent_id, policy_id)
);

COMMENT ON TABLE agent_policies IS '에이전트-정책 N:M 연결';


-- 2-5. certifications
CREATE TABLE certifications (
    certification_id UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    name             VARCHAR(255) NOT NULL,
    certifier_id     UUID         REFERENCES users(user_id),
    state            VARCHAR(20)  NOT NULL DEFAULT 'PENDING'
                         CHECK (state IN ('PENDING','PASSED','FAILED','REVOKED')),
    notes            TEXT,
    issued_at        TIMESTAMPTZ  DEFAULT now(),
    expires_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE certifications IS '에이전트 인증 레코드 — 거버넌스 팀에서 발급·관리';


-- 2-6. agent_certifications  (에이전트 ↔ 인증 N:M)
CREATE TABLE agent_certifications (
    agent_id          UUID        NOT NULL REFERENCES agents(agent_id)                ON DELETE CASCADE,
    certification_id  UUID        NOT NULL REFERENCES certifications(certification_id) ON DELETE CASCADE,
    linked_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, certification_id)
);

COMMENT ON TABLE agent_certifications IS '에이전트-인증 N:M 연결';


-- ===========================================================================
-- SECTION 3. 워크스페이스
-- ===========================================================================

-- 3-1. workspaces
CREATE TABLE workspaces (
    workspace_id UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    name         VARCHAR(255),
    owner_id     UUID         NOT NULL REFERENCES users(user_id),
    state        VARCHAR(20)  NOT NULL DEFAULT 'ACTIVE'
                     CHECK (state IN ('ACTIVE','ARCHIVED','DELETED')),
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE workspaces IS '사용자 작업 공간 — 목표·대화·메시지의 최상위 컨테이너';


-- 3-2. goals
CREATE TABLE goals (
    goal_id      UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID         NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    name         VARCHAR(255) NOT NULL,
    description  TEXT,
    state        VARCHAR(20)  NOT NULL DEFAULT 'ACTIVE'
                     CHECK (state IN ('ACTIVE','COMPLETED','CANCELLED')),
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE goals IS '워크스페이스 내 목표 — 종료 조건을 포함한 작업 단위';


-- ===========================================================================
-- SECTION 4. 대화 / UI 메시지
-- ===========================================================================

-- 4-1. conversations
CREATE TABLE conversations (
    conversation_id UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID         NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    goal_id         UUID         REFERENCES goals(goal_id),
    initiator_id    UUID         NOT NULL REFERENCES users(user_id),
    name            VARCHAR(255),
    role            VARCHAR(50),   -- 시작자의 역할 컨텍스트
    state           VARCHAR(20)   NOT NULL DEFAULT 'ACTIVE'
                        CHECK (state IN ('ACTIVE','COMPLETED','ARCHIVED')),
    schema_ver      VARCHAR(10)   NOT NULL DEFAULT '1.0',
    started_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ
);

COMMENT ON TABLE  conversations            IS '워크스페이스 내 대화 세션 — interactions의 상위 컨테이너';
COMMENT ON COLUMN conversations.schema_ver IS 'YAML 스키마 버전 — 마이그레이션 추적용';


-- 4-2. messages  (UI 표시용 — 채팅창에 보이는 메시지)
CREATE TABLE messages (
    message_id       UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id     UUID         NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    goal_id          UUID         REFERENCES goals(goal_id),
    conversation_id  UUID         REFERENCES conversations(conversation_id),
    interaction_id   UUID,        -- interactions.interaction_id (FK는 앱 레이어에서 검증)
    participant_id   UUID         NOT NULL,   -- users.user_id or agents.agent_id
    participant_type VARCHAR(10)  NOT NULL
                         CHECK (participant_type IN ('user','agent','system')),
    content          TEXT         NOT NULL,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE  messages                  IS 'UI 채팅창 표시용 메시지 — 에이전트 라우팅용 message_headers와 역할 분리';
COMMENT ON COLUMN messages.interaction_id   IS '연관 interaction 참조 (FK는 actor_type 혼합으로 앱 레이어 검증)';


-- ===========================================================================
-- SECTION 5. 메시지 라우팅 (Selective Consumption)
-- ===========================================================================

-- 5-1. message_headers  (라우팅 인덱스 — 에이전트가 폴링하는 경량 헤더)
CREATE TABLE message_headers (
    message_id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    -- 발신자
    sender_id          UUID         NOT NULL,   -- users.user_id or agents.agent_id
    sender_type        VARCHAR(10)  NOT NULL CHECK (sender_type IN ('user','agent','system')),
    sender_name        VARCHAR(255),
    -- 메시지 분류 (수신 판단 기준)
    domain             VARCHAR(100),            -- 도메인 카테고리 (finance, hr …)
    intent             VARCHAR(100),            -- 의도 유형 (data_request, alert …)
    priority           VARCHAR(10)  NOT NULL DEFAULT 'medium'
                           CHECK (priority IN ('low','medium','high','critical')),
    tags               TEXT[]       NOT NULL DEFAULT '{}',
    -- 라우팅 힌트
    target_ids         UUID[]       NOT NULL DEFAULT '{}',  -- 직접 지목 수신자
    target_roles       TEXT[]       NOT NULL DEFAULT '{}',  -- 역할 기반 수신
    scope              VARCHAR(20)  NOT NULL DEFAULT 'workspace'
                           CHECK (scope IN ('workspace','department','global')),
    -- 실행 컨텍스트
    execution_tree_id  UUID,        -- 어떤 A2A 실행 트리에 속하는지
    workspace_id       UUID         REFERENCES workspaces(workspace_id),
    conversation_id    UUID         REFERENCES conversations(conversation_id),
    -- 바디 참조 (헤더·바디 분리)
    body_ref           TEXT         NOT NULL,   -- messages.message_id or S3 key
    -- 시간 및 상태
    sent_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at         TIMESTAMPTZ,
    processed_count    INTEGER      NOT NULL DEFAULT 0  -- 소비한 에이전트 수
);

COMMENT ON TABLE  message_headers          IS 'Selective Consumption 라우팅 인덱스 — 에이전트가 헤더만 폴링하여 수신 여부 결정';
COMMENT ON COLUMN message_headers.body_ref IS '바디 위치 참조 — 초기: messages.message_id, 확장: S3 key';
COMMENT ON COLUMN message_headers.tags     IS 'GIN 인덱스로 태그 기반 빠른 필터링';


-- 5-2. message_receipts  (수신/거부 이력)
CREATE TABLE message_receipts (
    receipt_id  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id  UUID        NOT NULL,   -- message_headers.message_id
    agent_id    UUID        NOT NULL REFERENCES agents(agent_id),
    decision    VARCHAR(10) NOT NULL
                    CHECK (decision IN ('consumed','ignored','expired','failed')),
    decided_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason      TEXT,       -- 거부·실패 이유 (디버깅용)
    UNIQUE (message_id, agent_id)       -- 에이전트당 한 번만 결정
);

COMMENT ON TABLE message_receipts IS '에이전트별 메시지 수신·거부 이력 — 디버깅 및 감사용';


-- ===========================================================================
-- SECTION 6. 상호작용 (A2A + Human-Agent)
-- ===========================================================================

-- 6-1. interactions  (핫 테이블 — 최근 90일)
CREATE TABLE interactions (
    interaction_id      UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id     UUID         NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    schema_ver          VARCHAR(10)  NOT NULL DEFAULT '1.0',
    -- A2A 실행 트리 구조
    parent_id           UUID         REFERENCES interactions(interaction_id),
    execution_tree_id   UUID,        -- 루트부터 말단까지 동일 값 공유
    tree_depth          INTEGER      NOT NULL DEFAULT 0,   -- 루트=0, 서브=1 …
    tree_path           TEXT,        -- 'root/sub-A/peer-001' 역정규화 경로
    parallel_group_id   UUID,        -- 병렬 fork 묶음 (같은 값 = 동시 실행 형제)
    -- 위임 방식
    delegation_type     VARCHAR(20)
                            CHECK (delegation_type IN (
                                'user_request',   -- 사람 → 에이전트
                                'orchestration',  -- 오케스트레이터 → 서브 에이전트
                                'peer',           -- 에이전트 ↔ 에이전트 횡적 협업
                                'pipeline',       -- 순차 파이프라인
                                'parallel'        -- 병렬 fork
                            )),
    -- 시간
    start_timestamp     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    complete_timestamp  TIMESTAMPTZ,
    duration_ms         INTEGER,
    -- 발신자
    actor_type          VARCHAR(10)  NOT NULL CHECK (actor_type IN ('user','agent','system')),
    actor_id            UUID         NOT NULL,   -- users.user_id or agents.agent_id
    actor_name          VARCHAR(255) NOT NULL,
    -- 수신자
    target_type         VARCHAR(10)  CHECK (target_type IN ('user','agent','broadcast')),
    target_id           UUID,        -- users.user_id or agents.agent_id
    target_name         VARCHAR(255),
    -- 내용
    kind                VARCHAR(20)  NOT NULL DEFAULT 'message'
                            CHECK (kind IN (
                                'message',      -- 일반 메시지
                                'tool_call',    -- 도구 호출
                                'tool_result',  -- 도구 결과
                                'reasoning',    -- 추론 과정
                                'handoff',      -- 제어권 이전
                                'error'         -- 오류
                            )),
    step_id             INTEGER,
    prompt              TEXT,
    parameters          JSONB        NOT NULL DEFAULT '{}',
    results             TEXT,
    reasoning_trace     TEXT,        -- Chain-of-Thought 전체 (대용량 주의)
    tool_name           VARCHAR(255),
    tool_input          JSONB,
    tool_output         JSONB,
    -- 오케스트레이션
    involved_agents     UUID[]       NOT NULL DEFAULT '{}',
    -- 상태
    state               VARCHAR(20)  NOT NULL DEFAULT 'PENDING'
                            CHECK (state IN ('PENDING','RUNNING','COMPLETED','FAILED','CANCELLED')),
    error_code          VARCHAR(100),
    error_message       TEXT,
    -- 비용/성능
    token_input         INTEGER,
    token_output        INTEGER,
    model_used          VARCHAR(100),
    metadata            JSONB        NOT NULL DEFAULT '{}'
);

COMMENT ON TABLE  interactions                IS '모든 상호작용 기록 — 사람↔에이전트, 에이전트↔에이전트 통합';
COMMENT ON COLUMN interactions.execution_tree_id IS '루트 요청부터 말단까지 동일 — 전체 트리 한 번에 조회 가능';
COMMENT ON COLUMN interactions.tree_path         IS '역정규화 경로 — 재귀 CTE 없이 상위/하위 노드 검색';
COMMENT ON COLUMN interactions.parallel_group_id IS '같은 값 = 동시 fork된 형제 관계';
COMMENT ON COLUMN interactions.delegation_type   IS '위임 방식 — 오케스트레이션/피어/파이프라인/병렬 구분';
COMMENT ON COLUMN interactions.reasoning_trace   IS 'CoT 전체 텍스트 — 볼륨 증가 시 S3 이관 고려';


-- 6-2. interaction_archive  (콜드 테이블 — 감사·파인튜닝·재현용)
CREATE TABLE interaction_archive (
    LIKE interactions INCLUDING ALL,
    archived_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_immutable  BOOLEAN     NOT NULL DEFAULT true   -- Phase 4 불변성 플래그
);

COMMENT ON TABLE interaction_archive IS '90일 경과 interactions 이관 — 감사·파인튜닝·재현용 콜드 스토리지';


-- ===========================================================================
-- SECTION 7. 공지
-- ===========================================================================

CREATE TABLE notices (
    notice_id   UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    title       VARCHAR(255) NOT NULL,
    body        TEXT,
    target_role VARCHAR(50)  NOT NULL DEFAULT 'all'
                    CHECK (target_role IN (
                        'all','agent_owner','agent_engineer',
                        'trust_ops','governance','evaluator',
                        'ethics_liaison','release_manager'
                    )),
    is_active   BOOLEAN      NOT NULL DEFAULT true,
    created_by  UUID         REFERENCES users(user_id),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ
);

COMMENT ON TABLE notices IS '역할별 공지 및 온보딩 가이드';


-- ===========================================================================
-- INDEXES
-- ===========================================================================

-- users
CREATE INDEX idx_users_email      ON users(email);
CREATE INDEX idx_users_idp        ON users(idp_sub, idp_iss) WHERE idp_sub IS NOT NULL;
CREATE INDEX idx_users_state      ON users(state)            WHERE state = 'ACTIVE';

-- user_roles
CREATE INDEX idx_user_roles_role  ON user_roles(role);

-- agents
CREATE INDEX idx_agents_owner     ON agents(owner_id);
CREATE INDEX idx_agents_status    ON agents(status);
CREATE INDEX idx_agents_vis       ON agents(visibility);

-- agent_subscription_rules
CREATE INDEX idx_asr_agent        ON agent_subscription_rules(agent_id) WHERE is_active = true;
CREATE INDEX idx_asr_domains      ON agent_subscription_rules USING GIN(watch_domains);
CREATE INDEX idx_asr_intents      ON agent_subscription_rules USING GIN(watch_intents);
CREATE INDEX idx_asr_tags         ON agent_subscription_rules USING GIN(watch_tags);

-- workspaces
CREATE INDEX idx_ws_owner         ON workspaces(owner_id);
CREATE INDEX idx_ws_state         ON workspaces(state) WHERE state = 'ACTIVE';

-- goals
CREATE INDEX idx_goals_ws         ON goals(workspace_id);

-- conversations
CREATE INDEX idx_conv_ws          ON conversations(workspace_id);
CREATE INDEX idx_conv_goal        ON conversations(goal_id);
CREATE INDEX idx_conv_initiator   ON conversations(initiator_id);

-- messages (UI)
CREATE INDEX idx_msg_conv         ON messages(conversation_id, created_at DESC);
CREATE INDEX idx_msg_participant  ON messages(participant_id);

-- message_headers (라우팅 핵심 인덱스)
CREATE INDEX idx_mh_domain        ON message_headers(domain);
CREATE INDEX idx_mh_intent        ON message_headers(intent);
CREATE INDEX idx_mh_priority      ON message_headers(priority);
CREATE INDEX idx_mh_tags          ON message_headers USING GIN(tags);
CREATE INDEX idx_mh_target_ids    ON message_headers USING GIN(target_ids);
CREATE INDEX idx_mh_target_roles  ON message_headers USING GIN(target_roles);
CREATE INDEX idx_mh_expires       ON message_headers(expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX idx_mh_tree          ON message_headers(execution_tree_id);
CREATE INDEX idx_mh_sent          ON message_headers(sent_at DESC);

-- message_receipts
CREATE INDEX idx_mr_message       ON message_receipts(message_id);
CREATE INDEX idx_mr_agent         ON message_receipts(agent_id, decided_at DESC);
CREATE INDEX idx_mr_decision      ON message_receipts(decision);

-- interactions (A2A 트리 추적 핵심)
CREATE INDEX idx_inter_conv       ON interactions(conversation_id, start_timestamp DESC);
CREATE INDEX idx_inter_tree       ON interactions(execution_tree_id);
CREATE INDEX idx_inter_path       ON interactions(tree_path);
CREATE INDEX idx_inter_parent     ON interactions(parent_id)          WHERE parent_id IS NOT NULL;
CREATE INDEX idx_inter_parallel   ON interactions(parallel_group_id)  WHERE parallel_group_id IS NOT NULL;
CREATE INDEX idx_inter_actor      ON interactions(actor_id, start_timestamp DESC);
CREATE INDEX idx_inter_target     ON interactions(target_id);
CREATE INDEX idx_inter_state      ON interactions(state);
CREATE INDEX idx_inter_agents     ON interactions USING GIN(involved_agents);
CREATE INDEX idx_inter_schema     ON interactions(schema_ver);

-- notices
CREATE INDEX idx_notices_active   ON notices(is_active, target_role) WHERE is_active = true;


-- ===========================================================================
-- TRIGGERS  updated_at 자동 갱신
-- ===========================================================================

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_agents_updated_at
    BEFORE UPDATE ON agents FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_workspaces_updated_at
    BEFORE UPDATE ON workspaces FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_goals_updated_at
    BEFORE UPDATE ON goals FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_policies_updated_at
    BEFORE UPDATE ON policies FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_asr_updated_at
    BEFORE UPDATE ON agent_subscription_rules FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ===========================================================================
-- ARCHIVE JOB  (pg_cron 설치 후 주석 해제)
-- ===========================================================================
-- SELECT cron.schedule('archive-interactions', '0 3 * * *', $$
--     WITH moved AS (
--         DELETE FROM interactions
--         WHERE start_timestamp < now() - INTERVAL '90 days'
--         RETURNING *
--     )
--     INSERT INTO interaction_archive
--     SELECT *, now(), true FROM moved;
-- $$);
