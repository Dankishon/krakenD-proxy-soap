#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[smoke] docker compose up -d --build"
docker compose up -d --build

echo "[smoke] wait for startup"
sleep 6

SOAP_OK='<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:cx="urn:cx">
  <soapenv:Header/>
  <soapenv:Body>
    <cx:GetCxRequest>
      <cx:clientId>7</cx:clientId>
      <cx:firstName>Jane</cx:firstName>
      <cx:lastName>Doe</cx:lastName>
      <cx:requestId>smoke-ok-001</cx:requestId>
    </cx:GetCxRequest>
  </soapenv:Body>
</soapenv:Envelope>'

OK_FILE="/tmp/soap_ok.xml"
OK_STATUS="$(curl -sS -o "$OK_FILE" -w "%{http_code}" \
  -H "Content-Type: text/xml; charset=utf-8" \
  -X POST "http://localhost:8080/soap/cx" \
  --data "$SOAP_OK")"

echo "[smoke] success status=$OK_STATUS"
if [[ "$OK_STATUS" != "200" ]]; then
  echo "[smoke] expected HTTP 200"
  cat "$OK_FILE"
  exit 1
fi

grep -q "<soapenv:Envelope" "$OK_FILE"
grep -q "<cx:status>OK</cx:status>" "$OK_FILE"
grep -q "<cx:fullName>Jane Doe</cx:fullName>" "$OK_FILE"
grep -q "<cx:field01>value-1-smoke-ok-001</cx:field01>" "$OK_FILE"

SOAP_ERR='<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:cx="urn:cx">
  <soapenv:Body>
    <cx:GetCxRequest>
      <cx:clientId>-1</cx:clientId>
      <cx:firstName>Error</cx:firstName>
      <cx:lastName>Case</cx:lastName>
      <cx:requestId>smoke-fault-001</cx:requestId>
    </cx:GetCxRequest>
  </soapenv:Body>
</soapenv:Envelope>'

ERR_FILE="/tmp/soap_err.xml"
ERR_STATUS="$(curl -sS -o "$ERR_FILE" -w "%{http_code}" \
  -H "Content-Type: text/xml; charset=utf-8" \
  -X POST "http://localhost:8080/soap/cx" \
  --data "$SOAP_ERR")"

echo "[smoke] error status=$ERR_STATUS"
if [[ "$ERR_STATUS" != "500" ]]; then
  echo "[smoke] expected HTTP 500 for GraphQL error"
  cat "$ERR_FILE"
  exit 1
fi

grep -q "<soapenv:Fault>" "$ERR_FILE"
grep -q "GraphQL error" "$ERR_FILE"

echo "[smoke] waiting 2s for traces export"
sleep 2

echo "[smoke] all checks passed"
echo "[smoke] Откройте Jaeger UI: http://localhost:16686"
echo "[smoke] В поиске выберите service=krakend или service=graphql-svc и интервал Last 15 minutes"
