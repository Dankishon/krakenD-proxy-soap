# KrakenD Go plugin: SOAP -> GraphQL -> SOAP

Полностью воспроизводимый pet-проект на Docker Compose.

## Что демонстрируется

- `svc_a` (legacy SOAP клиент) отправляет SOAP XML в `krakend`.
- `krakend` через Go plugin:
  1. читает SOAP request,
  2. извлекает `clientId`, `firstName`, `lastName`, `requestId`,
  3. формирует GraphQL JSON,
  4. вызывает отдельный сервис `graphql_svc`,
  5. маппит `data.getCxData.*` в SOAP response (32 поля),
  6. возвращает SOAP XML клиенту.
- Отдельного SOAP adapter сервиса нет. Конвертация SOAP<->GraphQL делается внутри KrakenD plugin.

## Сервисы

- `krakend` -> [http://localhost:8080](http://localhost:8080)
- `svc_a` -> [http://localhost:8001](http://localhost:8001)
- `web_ui` -> [http://localhost:8002](http://localhost:8002)
- `graphql_svc` -> внутри docker-сети `http://graphql_svc:8000/graphql`

## Быстрый старт

```bash
docker compose up --build
```

## Структура

```text
.
├── docker-compose.yml
├── mapping.json
├── krakend
│   ├── Dockerfile
│   └── krakend.json
├── plugin
│   ├── go.mod
│   └── main.go
├── graphql_svc
│   ├── Dockerfile
│   └── main.py
├── svc_a
│   ├── Dockerfile
│   ├── main.py
│   └── templates/index.html
├── web_ui
│   ├── Dockerfile
│   ├── main.py
│   └── templates/index.html
└── scripts
    └── smoke.sh
```

## SOAP контракт (SOAP 1.1)

`Content-Type: text/xml; charset=utf-8`

Namespaces:

- `soapenv`: `http://schemas.xmlsoap.org/soap/envelope/`
- `cx`: `urn:cx`

### SOAP request поля

- `clientId` (int)
- `firstName` (string)
- `lastName` (string)
- `requestId` (string)

### SOAP response поля (32)

- `clientId`
- `requestId`
- `status`
- `fullName`
- `score`
- `field01..field27`

### SOAP Fault

Если GraphQL вернул `errors`, KrakenD возвращает:

- HTTP `500`
- SOAP Fault (`faultcode=soapenv:Server`)

## GraphQL

Endpoint: `POST http://graphql_svc:8000/graphql`

Query:

```graphql
query GetCxData($clientId:Int!,$firstName:String!,$lastName:String!,$requestId:String!){
  getCxData(clientId:$clientId, firstName:$firstName, lastName:$lastName, requestId:$requestId){
    clientId
    requestId
    status
    fullName
    score
    field01
    ...
    field27
  }
}
```

Поведение:

- `status = "OK"`
- `fullName = firstName + " " + lastName`
- `score = clientId * 1.23`
- `field01..field27 = "value-<n>-<requestId>"`
- при `clientId = -1` GraphQL возвращает ошибку

## mapping.json (source of truth)

- `input`: SOAP поля -> GraphQL variables
- `output`: GraphQL path -> SOAP поля ответа

Go plugin загружает этот файл при старте и применяет его в рантайме.

## UI

### svc_a (`:8001`)

- `GET /` — русская форма SOAP клиента
- `POST /call` — отправка SOAP в KrakenD
- Выводит SOAP запрос, HTTP статус, SOAP ответ и расшифровку ключевых полей

### web_ui (`:8002`)

- Русский интерфейс для демонстрации пайплайна
- Блоки:
  - ввод параметров,
  - шаги обработки (SOAP -> GraphQL -> JSON -> SOAP),
  - таблица маппинга,
  - результат (status/fullName/score/field01/field02/field03)
- Endpoint `POST /debug-run`:
  - формирует SOAP request,
  - вызывает KrakenD,
  - делает прямой вызов GraphQL для показа raw JSON,
  - возвращает все шаги для UI.

## Проверка curl

Успех:

```bash
curl -sS -X POST http://localhost:8080/soap/cx \
  -H 'Content-Type: text/xml; charset=utf-8' \
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

Ошибка (GraphQL -> SOAP Fault):

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

## Smoke тесты

```bash
./scripts/smoke.sh
```

Скрипт:

1. поднимает compose,
2. проверяет успешный SOAP ответ,
3. проверяет SOAP Fault для `clientId=-1`.
