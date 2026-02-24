import logging
import os

from ariadne import QueryType, gql, make_executable_schema
from ariadne.asgi import GraphQL
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from graphql import GraphQLError
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

OTLP_HTTP_ENDPOINT = os.getenv("OTLP_HTTP_ENDPOINT", "http://jaeger:4318")
OTLP_TRACES_ENDPOINT = os.getenv(
    "OTLP_TRACES_ENDPOINT", f"{OTLP_HTTP_ENDPOINT.rstrip('/')}/v1/traces"
)
SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "graphql-svc")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("graphql_svc")


def make_schema_text() -> str:
    fields = "\n".join([f"  field{i:02d}: String!" for i in range(1, 28)])
    return f"""
    type Query {{
      getCxData(clientId:Int!, firstName:String!, lastName:String!, requestId:String!): CxResult!
    }}

    type CxResult {{
      clientId: Int!
      requestId: String!
      status: String!
      fullName: String!
      score: Float!
{fields}
    }}
    """


def current_trace_id() -> str:
    span_context = trace.get_current_span().get_span_context()
    if span_context and span_context.is_valid:
        return f"{span_context.trace_id:032x}"
    return ""


type_defs = gql(make_schema_text())
query = QueryType()


@query.field("getCxData")
def resolve_get_cx_data(_, info, clientId: int, firstName: str, lastName: str, requestId: str):
    trace_id = current_trace_id()
    logger.info("resolve_getCxData clientId=%s requestId=%s trace_id=%s", clientId, requestId, trace_id)

    if clientId == -1:
        raise GraphQLError("clientId=-1 triggers demo GraphQL error")

    result = {
        "clientId": clientId,
        "requestId": requestId,
        "status": "OK",
        "fullName": f"{firstName} {lastName}".strip(),
        "score": round(clientId * 1.23, 2),
    }

    for i in range(1, 28):
        result[f"field{i:02d}"] = f"value-{i}-{requestId}"

    return result


schema = make_executable_schema(type_defs, query)
graphql_app = GraphQL(schema, debug=False)

app = FastAPI(title="graphql_svc")
app.add_route("/graphql", graphql_app, methods=["GET", "POST", "OPTIONS"])
app.add_websocket_route("/graphql", graphql_app)


@app.middleware("http")
async def append_trace_header(request: Request, call_next):
    response = await call_next(request)
    trace_id = current_trace_id()
    if trace_id:
        response.headers["X-Trace-Id"] = trace_id
    return response


@app.get("/health")
def health():
    payload = {"status": "ok", "traceId": current_trace_id()}
    response = JSONResponse(payload)
    if payload["traceId"]:
        response.headers["X-Trace-Id"] = payload["traceId"]
    return response


def setup_telemetry() -> None:
    resource = Resource.create({"service.name": SERVICE_NAME})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=OTLP_TRACES_ENDPOINT)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    RequestsInstrumentor().instrument()


setup_telemetry()
