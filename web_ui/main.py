import json
import os
from html import escape

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"
SOAP_CX_NS = "urn:cx"
MAPPING_FILE = os.getenv("MAPPING_FILE", "/app/mapping.json")
KRAKEND_BROWSER_URL = os.getenv("KRAKEND_BROWSER_URL", "http://localhost:8080/soap/cx")
GRAPHQL_TARGET_URL = os.getenv("GRAPHQL_TARGET_URL", "http://graphql_svc:8000/graphql")
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

app = FastAPI(title="web_ui demo")
templates = Jinja2Templates(directory="templates")


def setup_telemetry() -> None:
    resource = Resource.create({"service.name": SERVICE_NAME})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=OTLP_TRACES_ENDPOINT)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)


setup_telemetry()


def current_trace_id() -> str:
    span_context = trace.get_current_span().get_span_context()
    if span_context and span_context.is_valid:
        return f"{span_context.trace_id:032x}"
    return ""


def attach_trace_header(response: Response) -> None:
    trace_id = current_trace_id()
    if trace_id:
        response.headers["X-Trace-Id"] = trace_id


def load_mapping() -> dict:
    with open(MAPPING_FILE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def build_soap_request(client_id: int, first_name: str, last_name: str, request_id: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
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
"""


def build_graphql_request(values: dict, mapping: dict) -> dict:
    variables = {}
    for soap_field, target in mapping["input"].items():
        if not target.startswith("variables."):
            continue
        variables[target.removeprefix("variables.")] = values.get(soap_field)
    return {"query": GRAPHQL_QUERY, "variables": variables}


def jaeger_search_url(service_name: str) -> str:
    return f"{JAEGER_UI_URL}/search?service={service_name}"


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    mapping = load_mapping()
    defaults = {"clientId": 101, "firstName": "Иван", "lastName": "Петров", "requestId": "req-ui-001"}
    soap_preview = build_soap_request(
        defaults["clientId"], defaults["firstName"], defaults["lastName"], defaults["requestId"]
    )
    graphql_preview = json.dumps(build_graphql_request(defaults, mapping), indent=2, ensure_ascii=False)

    response = templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "defaults": defaults,
            "soap_preview": soap_preview,
            "graphql_preview": graphql_preview,
            "input_rows": [{"soap": k, "graphql": v} for k, v in mapping["input"].items()],
            "output_rows": [{"soap": k, "graphql": v} for k, v in mapping["output"].items()],
            "krakend_browser_url": KRAKEND_BROWSER_URL,
            "graphql_target_url": GRAPHQL_TARGET_URL,
            "jaeger_ui_url": JAEGER_UI_URL,
            "jaeger_search_krakend": jaeger_search_url("krakend"),
            "jaeger_search_graphql": jaeger_search_url("graphql-svc"),
            "jaeger_search_web_ui": jaeger_search_url("web-ui"),
        },
    )
    attach_trace_header(response)
    return response


@app.get("/mapping")
def mapping_endpoint():
    response = JSONResponse(load_mapping())
    attach_trace_header(response)
    return response

