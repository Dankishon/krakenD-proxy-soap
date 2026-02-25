# KrakenD Go plugin: SOAP -> GraphQL -> SOAP + Jaeger tracing

Полностью воспроизводимый pet-проект на Docker Compose.

Основной поток:

`Browser UI -> KrakenD (/soap/cx, SOAP XML) -> graphql_svc (/graphql) -> KrakenD -> Browser UI`

Конвертация SOAP<->GraphQL выполняется **внутри KrakenD Go plugin**. Отдельного adapter-сервиса нет.

## Запуск

```bash
docker compose up --build
```

Сервисы:

- `krakend`: [http://localhost:8080](http://localhost:8080)
- `graphql_svc`: внутри docker-сети `http://graphql_svc:8000/graphql`
- `svc_a` (опциональный клиент): [http://localhost:8001](http://localhost:8001)
- `web_ui` (основной UI): [http://localhost:8002](http://localhost:8002)
- `jaeger`: [http://localhost:16686](http://localhost:16686)

## Что делает KrakenD plugin

Endpoint: `POST /soap/cx`

1. Читает raw SOAP XML.
2. Парсит `clientId`, `firstName`, `lastName`, `requestId`.
3. Формирует GraphQL JSON:
   - `query GetCxData(...)`
   - `variables`
4. Вызывает отдельный `graphql_svc` по HTTP POST `/graphql`.
5. Читает JSON `data.getCxData`.
6. Применяет `mapping.json`.
7. Возвращает SOAP XML (32 поля: `clientId`, `requestId`, `status`, `fullName`, `score`, `field01..field27`).
8. При ошибке GraphQL возвращает SOAP Fault и HTTP `500`.

## Debug headers для UI (Шаги 2-3)

KrakenD добавляет в ответ:

- `X-Trace-Id`
- `X-GraphQL-Query` (base64)
- `X-GraphQL-Vars` (base64 JSON)
- `X-GraphQL-Response` (base64 JSON)
- `X-GraphQL-Status` (`OK` или `ERROR`)
- `X-GraphQL-Error` (при ошибке)

`web_ui` декодирует эти заголовки и отображает:

- Шаг 1: SOAP запрос
- Шаг 2: GraphQL запрос (query + variables)
- Шаг 3: GraphQL ответ (JSON)
- Шаг 4: SOAP ответ

## CORS

В `krakend.json` включён `security/cors` для browser запроса с `http://localhost:8002`:

- methods: `POST`, `OPTIONS`
- allow headers: `Content-Type`, `SOAPAction`, `traceparent`, `tracestate`, `baggage`, `X-Trace-Id`
- expose headers: debug headers (`X-GraphQL-*`, `X-Trace-Id`)

## Tracing (OpenTelemetry + Jaeger)

Инструментировано:

- `krakend` (`telemetry/opentelemetry`)
- `graphql_svc` (FastAPI + OTLP exporter)
- `web_ui` (FastAPI + OTLP exporter)
- `svc_a` (FastAPI + OTLP exporter, опционально)

Чтобы упростить корреляцию, `web_ui` создаёт `traceparent` и отправляет его в KrakenD.

В UI есть кнопка:

- `Открыть трассу в Jaeger` -> `http://localhost:16686/trace/<traceId>` (если `traceId` известен)
- иначе ссылка ведёт на поиск по сервису `krakend`

Важно: browser DevTools не показывает server-to-server вызов `KrakenD -> GraphQL`. Этот участок виден в Jaeger.

## SOAP контракт (SOAP 1.1)

`Content-Type: text/xml; charset=utf-8`

Namespaces:

- `soapenv`: `http://schemas.xmlsoap.org/soap/envelope/`
- `cx`: `urn:cx`

Request поля:

- `clientId` (int)
- `firstName` (string)
- `lastName` (string)
- `requestId` (string)

Response поля (32):

- `clientId`, `requestId`, `status`, `fullName`, `score`, `field01..field27`

## GraphQL сервис

Endpoint: `POST http://graphql_svc:8000/graphql`

Логика:

- `status = "OK"`
- `fullName = firstName + " " + lastName`
- `score = clientId * 1.23`
- `field01..field27 = "value-<n>-<requestId>"`
- `clientId = -1` -> GraphQL error (демо)

## mapping.json

`mapping.json` — единый источник правды:

- `input`: SOAP -> GraphQL variables
- `output`: GraphQL path -> SOAP response fields

Плагин читает этот файл при старте KrakenD.

## Проверка curl (прямо в KrakenD)

Успех:

```bash
curl -si -X POST http://localhost:8080/soap/cx \
  -H 'Content-Type: text/xml; charset=utf-8' \
  -H 'traceparent: 00-1234567890abcdef1234567890abcdef-1234567890abcdef-01' \
  --data '<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:cx="urn:cx">
  <soapenv:Body>
    <cx:GetCxRequest>
      <cx:clientId>7</cx:clientId>
      <cx:firstName>Jane</cx:firstName>
      <cx:lastName>Doe</cx:lastName>
      <cx:requestId>manual-001</cx:requestId>
    </cx:GetCxRequest>
  </soapenv:Body>
</soapenv:Envelope>'
```

Ошибка (SOAP Fault):

```bash
curl -si -X POST http://localhost:8080/soap/cx \
  -H 'Content-Type: text/xml; charset=utf-8' \
  --data '<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:cx="urn:cx">
  <soapenv:Body>
    <cx:GetCxRequest>
      <cx:clientId>-1</cx:clientId>
      <cx:firstName>Error</cx:firstName>
      <cx:lastName>Case</cx:lastName>
      <cx:requestId>manual-fault-001</cx:requestId>
    </cx:GetCxRequest>
  </soapenv:Body>
</soapenv:Envelope>'
```

## Smoke test

```bash
./scripts/smoke.sh
```

Скрипт:

1. Поднимает compose.
2. Проверяет успешный SOAP response.
3. Проверяет debug headers (`X-GraphQL-*`, `X-Trace-Id`).
4. Проверяет SOAP Fault для `clientId=-1`.
5. Даёт подсказку открыть Jaeger.
