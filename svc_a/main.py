import os
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from html import escape

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"
SOAP_CX_NS = "urn:cx"
KRAKEND_URL = os.getenv("KRAKEND_URL", "http://krakend:8080/soap/cx")

NS = {"soapenv": SOAP_ENV_NS, "cx": SOAP_CX_NS}

app = FastAPI(title="svc_a legacy SOAP client")
templates = Jinja2Templates(directory="templates")


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


def post_soap(xml_payload: str) -> tuple[int, str]:
    req = urllib.request.Request(
        KRAKEND_URL,
        method="POST",
        data=xml_payload.encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def decode_key_fields(soap_xml: str) -> dict:
    try:
        root = ET.fromstring(soap_xml)
    except ET.ParseError:
        return {"error": "Невалидный XML в ответе"}

    result = {}
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
    return templates.TemplateResponse(
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


@app.post("/call", response_class=HTMLResponse)
def call(
    request: Request,
    clientId: int = Form(...),
    firstName: str = Form(...),
    lastName: str = Form(...),
    requestId: str = Form(...),
):
    soap_request = build_soap_request(clientId, firstName, lastName, requestId)
    status, soap_response = post_soap(soap_request)
    decoded = decode_key_fields(soap_response)

    return templates.TemplateResponse(
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
            },
            "krakend_url": KRAKEND_URL,
        },
    )


@app.get("/demo")
def demo(
    clientId: int = Query(101),
    firstName: str = Query("Иван"),
    lastName: str = Query("Петров"),
    requestId: str = Query("req-1001"),
):
    soap_request = build_soap_request(clientId, firstName, lastName, requestId)
    status, soap_response = post_soap(soap_request)
    return JSONResponse(
        {
            "krakendUrl": KRAKEND_URL,
            "status": status,
            "soapRequest": soap_request,
            "soapResponse": soap_response,
            "decoded": decode_key_fields(soap_response),
        }
    )
