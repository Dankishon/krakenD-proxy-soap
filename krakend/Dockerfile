FROM krakend/builder:2.13.0 AS plugin-builder

WORKDIR /src/plugin
COPY plugin/go.mod ./go.mod
COPY plugin/main.go ./main.go
RUN go build -buildmode=plugin -o /tmp/soap_graphql.so .

FROM krakend:2.13

COPY krakend/krakend.json /etc/krakend/krakend.json
COPY mapping.json /etc/krakend/mapping.json
COPY --from=plugin-builder /tmp/soap_graphql.so /etc/krakend/plugins/soap_graphql.so

CMD ["run", "-c", "/etc/krakend/krakend.json"]
