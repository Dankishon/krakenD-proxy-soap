import json
import os
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from html import escape

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"
SOAP_CX_NS = "urn:cx"
NS = {"soapenv": SOAP_ENV_NS, "cx": SOAP_CX_NS}

KRAKEND_URL = os.getenv("KRAKEND_URL", "http://krakend:8080/soap/cx")
GRAPHQL_URL = os.getenv("GRAPHQL_URL", "http://graphql_svc:8000/graphql")
MAPPING_FILE = os.getenv("MAPPING_FILE", "/app/mapping.json")

OUTPUT_ORDER = [
    "clientId",
    "requestId",
    "status",
    "fullName",
    "score",
    *[f"field{i:02d}" for i in range(1, 28)],
]

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


def post_text(url: str, body: str, content_type: str) -> tuple[int, str]:
    req = urllib.request.Request(
        url,
        method="POST",
        data=body.encode("utf-8"),
        headers={"Content-Type": content_type},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


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

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "defaults": defaults,
            "soap_preview": soap_preview,
            "graphql_preview": gql_preview,
            "mapping": mapping,
            "input_rows": input_rows,
            "output_rows": output_rows,
            "krakend_url": KRAKEND_URL,
            "graphql_url": GRAPHQL_URL,
        },
    )


@app.get("/mapping")
def mapping_endpoint():
    return JSONResponse(load_mapping())


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

    soap_status, soap_response = post_text(KRAKEND_URL, soap_request, "text/xml; charset=utf-8")
    gql_status, gql_response_raw = post_text(
        GRAPHQL_URL,
        json.dumps(gql_request, ensure_ascii=False),
        "application/json",
    )

    gql_response = parse_json(gql_response_raw)

    return JSONResponse(
        {
            "soapRequest": soap_request,
            "graphqlRequest": gql_request,
            "graphqlStatus": gql_status,
            "graphqlResponse": gql_response,
            "soapStatus": soap_status,
            "soapResponse": soap_response,
            "result": parse_key_values(soap_response),
            "errors": gql_response.get("errors", []),
        }
    )
