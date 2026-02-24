from ariadne import QueryType, gql, make_executable_schema
from ariadne.asgi import GraphQL
from fastapi import FastAPI
from graphql import GraphQLError


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


type_defs = gql(make_schema_text())
query = QueryType()


@query.field("getCxData")
def resolve_get_cx_data(_, info, clientId: int, firstName: str, lastName: str, requestId: str):
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


@app.get("/health")
def health():
    return {"status": "ok"}
