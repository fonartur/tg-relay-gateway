-- tg-relay: проекты, ключи и учёт потребления.
-- Ни в одной таблице нет токенов ботов — только отпечатки (12 hex-символов SHA-256).
-- Счётчики пишутся через INSERT ... ON CONFLICT DO UPDATE с прибавлением,
-- поэтому несколько узлов шлюза не затирают друг друга.

CREATE TABLE IF NOT EXISTS projects (
    id                  SERIAL      PRIMARY KEY,
    name                TEXT        NOT NULL,
    enabled             BOOLEAN     NOT NULL DEFAULT TRUE,
    rate_limit          INTEGER     NOT NULL DEFAULT 30 CHECK (rate_limit >= 0),         -- запросов/с, 0 = без лимита
    monthly_bot_limit   INTEGER     NOT NULL DEFAULT 0  CHECK (monthly_bot_limit >= 0),  -- 0 = без лимита
    monthly_byte_limit  BIGINT      NOT NULL DEFAULT 0  CHECK (monthly_byte_limit >= 0), -- 0 = без лимита
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Несколько ключей на проект — ротация без простоя.
-- Хранится SHA-256 ключа (hex); сам ключ не хранится нигде.
CREATE TABLE IF NOT EXISTS project_keys (
    key_hash    TEXT        PRIMARY KEY,
    project_id  INTEGER     NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    enabled     BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS project_keys_project_id_idx ON project_keys(project_id);

-- Трафик и число запросов проекта за расчётный месяц.
CREATE TABLE IF NOT EXISTS usage_counters (
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    month       DATE    NOT NULL,            -- первое число расчётного месяца
    requests    BIGINT  NOT NULL DEFAULT 0,
    bytes_out   BIGINT  NOT NULL DEFAULT 0,  -- upstream -> клиент
    bytes_in    BIGINT  NOT NULL DEFAULT 0,  -- клиент -> upstream
    PRIMARY KEY (project_id, month)
);

-- Активные боты: уникальные отпечатки токенов за месяц — единица тарификации.
CREATE TABLE IF NOT EXISTS active_bots (
    project_id  INTEGER     NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    month       DATE        NOT NULL,
    fingerprint TEXT        NOT NULL,
    first_seen  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, month, fingerprint)
);
