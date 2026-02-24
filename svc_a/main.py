import logging
import os
import xml.etree.ElementTree as ET
from html import escape

import requests
from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"
SOAP_CX_NS = "urn:cx"
KRAKEND_URL = os.getenv("KRAKEND_URL", "http://krakend:8080/soap/cx")
OTLP_HTTP_ENDPOINT = os.getenv("OTLP_HTTP_ENDPOINT", "http://jaeger:4318")
OTLP_TRACES_ENDPOINT = os.getenv(
    "OTLP_TRACES_ENDPOINT", f"{OTLP_HTTP_ENDPOINT.rstrip('/')}/v1/traces"
)
SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "svc-a")

NS = {"soapenv": SOAP_ENV_NS, "cx": SOAP_CX_NS}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("svc_a")

app = FastAPI(title="svc_a legacy SOAP client")
templates = Jinja2Templates(directory="templates")


def setup_telemetry() -> None:
    resource = Resource.create({"service.name": SERVICE_NAME})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=OTLP_TRACES_ENDPOINT)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    RequestsInstrumentor().instrument()


setup_telemetry()


def current_trace_id() -> str:
    span_context = trace.get_current_span().get_span_context()
    if span_context and span_context.is_valid:
        return f"{span_context.trace_id:032x}"
    return ""


def attach_trace_header(response: Response) -> str:
    trace_id = current_trace_id()
    if trace_id:
        response.headers["X-Trace-Id"] = trace_id
    return trace_id


def build_soap_request(client_id: int, first_name: str, last_name: str, request_id: str) -> str:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="{SOAP_ENV_NS}" xmlns:cx="{SOAP_CX_NS}">
  <soapenv:Header/>
  <soapenv:Body>
    <cx:GetCxRequest>
      <cx:clientId>{escape(str(client_id))}</cx:clientId>
      <cx:firstName>{escape(first_name)}</cx:firstName>
      <cx:lastName>{escape(last_name)}</cx:lastName>
      <cx:requestId>{escape(request_id)}</cx:requestId>
    </cx:GetCxRequest>
  </soapenv:Body>
</soapenv:Envelope>
'''


def post_soap(xml_payload: str) -> tuple[int, str, dict[str, str]]:
    headers = {"Content-Type": "text/xml; charset=utf-8"}
    trace_id = current_trace_id()
    if trace_id:
        headers["X-Trace-Id"] = trace_id

    try:
        response = requests.post(KRAKEND_URL, data=xml_payload.encode("utf-8"), headers=headers, timeout=8)
        return response.status_code, response.text, dict(response.headers)
    except requests.RequestException as exc:
        logger.exception("SOAP call to KrakenD failed")
        return 502, f"Transport error: {exc}", {}


def get_header(headers: dict[str, str], name: str) -> str:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return ""


def decode_key_fields(soap_xml: str) -> dict[str, str]:
    try:
        root = ET.fromstring(soap_xml)
    except ET.ParseError:
        return {"error": "Невалидный XML в ответе"}

    result: dict[str, str] = {}
    for field in ["status", "fullName", "score", "field01"]:
        value = root.findtext(f".//cx:{field}", default="", namespaces=NS)
        if value:
            result[field] = value

    fault = root.findtext(".//faultstring")
    if fault:
        result["fault"] = fault

    if not result:
        result["info"] = "Ключевые поля не найдены"

    return result


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    response = templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "defaults": {
                "clientId": 101,
                "firstName": "Иван",
                "lastName": "Петров",
                "requestId": "req-1001",
            },
            "result": None,
            "krakend_url": KRAKEND_URL,
        },
    )
    attach_trace_header(response)
    return response


@app.post("/call", response_class=HTMLResponse)
def call(
    request: Request,
    clientId: int = Form(...),
    firstName: str = Form(...),
    lastName: str = Form(...),
    requestId: str = Form(...),
):
    soap_request = build_soap_request(clientId, firstName, lastName, requestId)
    status, soap_response, upstream_headers = post_soap(soap_request)
    decoded = decode_key_fields(soap_response)

    upstream_trace_id = get_header(upstream_headers, "X-Trace-Id")
    local_trace_id = current_trace_id()
    logger.info(
        "SOAP call completed status=%s local_trace_id=%s krakend_trace_id=%s",
        status,
        local_trace_id,
        upstream_trace_id,
    )

    response = templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "defaults": {
                "clientId": clientId,
                "firstName": firstName,
                "lastName": lastName,
                "requestId": requestId,
            },
            "result": {
                "status": status,
                "soap_request": soap_request,
                "soap_response": soap_response,
                "decoded": decoded,
                "trace_id": local_trace_id,
                "upstream_trace_id": upstream_trace_id,
            },
            "krakend_url": KRAKEND_URL,
        },
    )
    attach_trace_header(response)
    return response


@app.get("/demo")
def demo(
    clientId: int = Query(101),
    firstName: str = Query("Иван"),
    lastName: str = Query("Петров"),
    requestId: str = Query("req-1001"),
):
    soap_request = build_soap_request(clientId, firstName, lastName, requestId)
    status, soap_response, upstream_headers = post_soap(soap_request)
    local_trace_id = current_trace_id()
    krakend_trace_id = get_header(upstream_headers, "X-Trace-Id")
    logger.info(
        "demo call status=%s local_trace_id=%s krakend_trace_id=%s",
        status,
        local_trace_id,
        krakend_trace_id,
    )

    payload = {
        "krakendUrl": KRAKEND_URL,
        "status": status,
        "soapRequest": soap_request,
        "soapResponse": soap_response,
        "decoded": decode_key_fields(soap_response),
        "traceId": local_trace_id,
        "krakendTraceId": krakend_trace_id,
    }
    response = JSONResponse(payload)
    attach_trace_header(response)
    return response
