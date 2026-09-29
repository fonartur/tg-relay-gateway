-- tg-relay: статистика для дашбордов (включается STATS_ENABLED=true).
-- По-прежнему без токенов — только отпечатки.

-- Почасовые агрегаты: число запросов, ошибок, задержки.
CREATE TABLE IF NOT EXISTS request_stats (
    project_id INTEGER     NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    hour       TIMESTAMPTZ NOT NULL,
    requests   BIGINT      NOT NULL DEFAULT 0,
    errors     BIGINT      NOT NULL DEFAULT 0,
    sum_ms     BIGINT      NOT NULL DEFAULT 0,  -- для средней задержки
    p50_ms     INTEGER     NOT NULL DEFAULT 0,
    p95_ms     INTEGER     NOT NULL DEFAULT 0,
    PRIMARY KEY (project_id, hour)
);
CREATE INDEX IF NOT EXISTS request_stats_hour_idx ON request_stats(hour);

-- Журнал последних неудачных запросов (хранится не больше 500 на проект).
CREATE TABLE IF NOT EXISTS request_errors (
    id          BIGSERIAL   PRIMARY KEY,
    project_id  INTEGER     NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    fingerprint TEXT,
    method      TEXT,
    code        INTEGER,
    message     TEXT
);
CREATE INDEX IF NOT EXISTS request_errors_project_idx ON request_errors(project_id, id DESC);

-- Последний запрос проекта — для индикатора «бот подключён».
CREATE TABLE IF NOT EXISTS project_last_request (
    project_id  INTEGER     PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    ts          TIMESTAMPTZ NOT NULL,
    fingerprint TEXT,
    method      TEXT,
    code        INTEGER,
    duration_ms INTEGER
);
