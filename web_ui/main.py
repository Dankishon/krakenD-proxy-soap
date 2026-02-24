import json
import logging
import os
import xml.etree.ElementTree as ET
from html import escape

import requests
from fastapi import FastAPI, Request
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
NS = {"soapenv": SOAP_ENV_NS, "cx": SOAP_CX_NS}

KRAKEND_URL = os.getenv("KRAKEND_URL", "http://krakend:8080/soap/cx")
GRAPHQL_URL = os.getenv("GRAPHQL_URL", "http://graphql_svc:8000/graphql")
MAPPING_FILE = os.getenv("MAPPING_FILE", "/app/mapping.json")
JAEGER_UI_URL = os.getenv("JAEGER_UI_URL", "http://localhost:16686").rstrip("/")
OTLP_HTTP_ENDPOINT = os.getenv("OTLP_HTTP_ENDPOINT", "http://jaeger:4318")
OTLP_TRACES_ENDPOINT = os.getenv(
    "OTLP_TRACES_ENDPOINT", f"{OTLP_HTTP_ENDPOINT.rstrip('/')}/v1/traces"
)
SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "web-ui")

GRAPHQL_QUERY = """query GetCxData($clientId:Int!,$firstName:String!,$lastName:String!,$requestId:String!){
  getCxData(clientId:$clientId, firstName:$firstName, lastName:$lastName, requestId:$requestId){
    clientId
    requestId
    status
    fullName
    score
    field01
    field02
    field03
    field04
    field05
    field06
    field07
    field08
    field09
    field10
    field11
    field12
    field13
    field14
    field15
    field16
    field17
    field18
    field19
    field20
    field21
    field22
    field23
    field24
    field25
    field26
    field27
  }
}"""

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("web_ui")

app = FastAPI(title="web_ui demo")
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


def load_mapping() -> dict:
    with open(MAPPING_FILE, "r", encoding="utf-8") as fh:
        return json.load(fh)


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


def build_graphql_request(values: dict, mapping: dict) -> dict:
    variables = {}
    for soap_field, target in mapping["input"].items():
        if not target.startswith("variables."):
            continue
        variables[target.removeprefix("variables.")] = values.get(soap_field)
    return {"query": GRAPHQL_QUERY, "variables": variables}


def post_text(url: str, body: str, content_type: str) -> tuple[int, str, dict[str, str]]:
    headers = {"Content-Type": content_type}
    trace_id = current_trace_id()
    if trace_id:
        headers["X-Trace-Id"] = trace_id

    try:
        response = requests.post(url, data=body.encode("utf-8"), headers=headers, timeout=8)
        return response.status_code, response.text, dict(response.headers)
    except requests.RequestException as exc:
        logger.exception("HTTP request failed url=%s", url)
        return 502, f"Transport error: {exc}", {}


def get_header(headers: dict[str, str], name: str) -> str:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return ""


def parse_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw, "_parseError": "invalid JSON"}


def parse_key_values(soap_xml: str) -> dict:
    try:
        root = ET.fromstring(soap_xml)
    except ET.ParseError:
        return {"error": "Невалидный SOAP XML"}

    fault = root.findtext(".//faultstring")
    if fault:
        return {"fault": fault}

    result = {}
    for key in ["status", "fullName", "score", "field01", "field02", "field03"]:
        result[key] = root.findtext(f".//cx:{key}", default="", namespaces=NS)
    return result


def jaeger_search_url(service_name: str) -> str:
    return f"{JAEGER_UI_URL}/search?service={service_name}"


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    mapping = load_mapping()
    defaults = {"clientId": 101, "firstName": "Иван", "lastName": "Петров", "requestId": "req-ui-001"}

    soap_preview = build_soap_request(
        defaults["clientId"], defaults["firstName"], defaults["lastName"], defaults["requestId"]
    )
    gql_preview = json.dumps(build_graphql_request(defaults, mapping), indent=2, ensure_ascii=False)

    input_rows = [{"soap": k, "graphql": v} for k, v in mapping["input"].items()]
    output_rows = [{"soap": k, "graphql": v} for k, v in mapping["output"].items()]

    response = templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "defaults": defaults,
            "soap_preview": soap_preview,
            "graphql_preview": gql_preview,
            "input_rows": input_rows,
            "output_rows": output_rows,
            "krakend_url": KRAKEND_URL,
            "graphql_url": GRAPHQL_URL,
            "jaeger_ui_url": JAEGER_UI_URL,
            "jaeger_links": {
                "krakend": jaeger_search_url("krakend"),
                "graphql": jaeger_search_url("graphql-svc"),
                "web_ui": jaeger_search_url("web-ui"),
            },
        },
    )
    attach_trace_header(response)
    return response


@app.get("/mapping")
def mapping_endpoint():
    response = JSONResponse(load_mapping())
    attach_trace_header(response)
    return response


@app.post("/debug-run")
async def debug_run(request: Request):
    payload = await request.json()
    mapping = load_mapping()

    values = {
        "clientId": int(payload.get("clientId", 101)),
        "firstName": str(payload.get("firstName", "Иван")),
        "lastName": str(payload.get("lastName", "Петров")),
        "requestId": str(payload.get("requestId", "req-ui-001")),
    }

    soap_request = build_soap_request(values["clientId"], values["firstName"], values["lastName"], values["requestId"])
    gql_request = build_graphql_request(values, mapping)

    soap_status, soap_response, soap_headers = post_text(KRAKEND_URL, soap_request, "text/xml; charset=utf-8")
    gql_status, gql_response_raw, gql_headers = post_text(
        GRAPHQL_URL,
        json.dumps(gql_request, ensure_ascii=False),
        "application/json",
    )

    gql_response = parse_json(gql_response_raw)
    web_trace_id = current_trace_id()
    krakend_trace_id = get_header(soap_headers, "X-Trace-Id")
    graphql_trace_id = get_header(gql_headers, "X-Trace-Id")

    logger.info(
        "debug-run soap_status=%s gql_status=%s trace_ids web=%s krakend=%s graphql=%s",
        soap_status,
        gql_status,
        web_trace_id,
        krakend_trace_id,
        graphql_trace_id,
    )

    response = JSONResponse(
        {
            "soapRequest": soap_request,
            "graphqlRequest": gql_request,
            "graphqlStatus": gql_status,
            "graphqlResponse": gql_response,
            "soapStatus": soap_status,
            "soapResponse": soap_response,
            "result": parse_key_values(soap_response),
            "errors": gql_response.get("errors", []),
            "tracing": {
                "traceId": web_trace_id,
                "krakendTraceId": krakend_trace_id,
                "graphqlTraceId": graphql_trace_id,
                "jaeger": {
                    "krakend": jaeger_search_url("krakend"),
                    "graphql": jaeger_search_url("graphql-svc"),
                    "svc_a": jaeger_search_url("svc-a"),
                    "web_ui": jaeger_search_url("web-ui"),
                },
            },
        }
    )
    attach_trace_header(response)
    return response
