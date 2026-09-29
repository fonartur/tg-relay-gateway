# Changelog

Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии — [SemVer](https://semver.org/lang/ru/).

## [1.0.0] — 2026-09-26

Первый открытый выпуск шлюза, который работает в
[tg-relay.scriptora.ru](https://tg-relay.scriptora.ru).

### Добавлено

- Прозрачное проксирование Bot API: потоковая передача, long polling, загрузка и скачивание файлов.
- Проекты и ключи в PostgreSQL, CLI `tg-relay`, автономный режим без базы.
- Лимиты тарифа: запросы в секунду, боты и трафик в месяц.
- Почасовая статистика, журнал ошибок, «последний запрос» проекта.
- Метрики Prometheus, JSON-логи, `/healthz`, `/readyz`, корректная остановка.
