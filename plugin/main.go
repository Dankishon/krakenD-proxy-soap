package main

import (
	"bytes"
	"context"
	"encoding/json"
	"encoding/xml"
	"fmt"
	"io"
	"math"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"
)

const (
	pluginName         = "soap-graphql-plugin"
	soapContentType    = "text/xml; charset=utf-8"
	soapEnvNS          = "http://schemas.xmlsoap.org/soap/envelope/"
	soapCxNS           = "urn:cx"
	defaultPath        = "/soap/cx"
	defaultMethod      = "POST"
	defaultGraphQLURL  = "http://graphql_svc:8000/graphql"
	defaultMappingFile = "/etc/krakend/mapping.json"
)

var (
	// HandlerRegisterer is required by KrakenD to discover the plugin.
	HandlerRegisterer = registerer(pluginName)
	logger            Logger = noopLogger{}
)

var inputFields = []string{"clientId", "firstName", "lastName", "requestId"}

var outputFields = []string{
	"clientId",
	"requestId",
	"status",
	"fullName",
	"score",
	"field01",
	"field02",
	"field03",
	"field04",
	"field05",
	"field06",
	"field07",
	"field08",
	"field09",
	"field10",
	"field11",
	"field12",
	"field13",
	"field14",
	"field15",
	"field16",
	"field17",
	"field18",
	"field19",
	"field20",
	"field21",
	"field22",
	"field23",
	"field24",
	"field25",
	"field26",
	"field27",
}

type registerer string

type Logger interface {
	Debug(v ...interface{})
	Info(v ...interface{})
	Warning(v ...interface{})
	Error(v ...interface{})
	Critical(v ...interface{})
	Fatal(v ...interface{})
}

type noopLogger struct{}

func (noopLogger) Debug(v ...interface{})    {}
func (noopLogger) Info(v ...interface{})     {}
func (noopLogger) Warning(v ...interface{})  {}
func (noopLogger) Error(v ...interface{})    {}
func (noopLogger) Critical(v ...interface{}) {}
func (noopLogger) Fatal(v ...interface{})    {}

type pluginConfig struct {
	Path       string
	Method     string
	GraphQLURL string
	Mapping    string
	Timeout    time.Duration
}

type mappingSpec struct {
	Input  map[string]string `json:"input"`
	Output map[string]string `json:"output"`
}

type soapInput struct {
	ClientID  int
	FirstName string
	LastName  string
	RequestID string
}

type graphQLError struct {
	Message string `json:"message"`
}

type graphQLResponse struct {
	Data   map[string]interface{} `json:"data"`
	Errors []graphQLError         `json:"errors"`
}

func main() {}

func (r registerer) RegisterLogger(v interface{}) {
	if l, ok := v.(Logger); ok {
		logger = l
		logger.Info("[soap-graphql-plugin] logger registered")
	}
}

func (r registerer) RegisterHandlers(register func(string, func(context.Context, map[string]interface{}, http.Handler) (http.Handler, error))) {
	register(string(r), r.registerHandlers)
}

func (r registerer) registerHandlers(_ context.Context, extra map[string]interface{}, next http.Handler) (http.Handler, error) {
	cfg, err := parseConfig(extra)
	if err != nil {
		return nil, err
	}

	mapping, err := loadMapping(cfg.Mapping)
	if err != nil {
		return nil, err
	}

	gqlQuery := buildGraphQLQuery()
	client := &http.Client{Timeout: cfg.Timeout}

	logger.Info(fmt.Sprintf("[soap-graphql-plugin] enabled on %s %s", cfg.Method, cfg.Path))

	return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		if req.URL.Path != cfg.Path || strings.ToUpper(req.Method) != cfg.Method {
			next.ServeHTTP(w, req)
			return
		}
		handleSOAPRequest(w, req, client, cfg, mapping, gqlQuery)
	}), nil
}

func parseConfig(extra map[string]interface{}) (pluginConfig, error) {
	cfg := pluginConfig{
		Path:       defaultPath,
		Method:     defaultMethod,
		GraphQLURL: defaultGraphQLURL,
		Mapping:    defaultMappingFile,
		Timeout:    4500 * time.Millisecond,
	}

	rawCfg, ok := extra[pluginName]
	if !ok {
		return cfg, fmt.Errorf("missing config for %s", pluginName)
	}

	cfgMap, ok := rawCfg.(map[string]interface{})
	if !ok {
		return cfg, fmt.Errorf("invalid config type for %s", pluginName)
	}

	if v, ok := cfgMap["path"]; ok {
		cfg.Path = fmt.Sprintf("%v", v)
	}
	if v, ok := cfgMap["method"]; ok {
		cfg.Method = strings.ToUpper(fmt.Sprintf("%v", v))
	}
	if v, ok := cfgMap["graphql_url"]; ok {
		cfg.GraphQLURL = fmt.Sprintf("%v", v)
	}
	if v, ok := cfgMap["mapping_file"]; ok {
		cfg.Mapping = fmt.Sprintf("%v", v)
	}
	if v, ok := cfgMap["timeout_ms"]; ok {
		ms, err := toInt(v)
		if err != nil {
			return cfg, fmt.Errorf("invalid timeout_ms: %w", err)
		}
		if ms <= 0 {
			return cfg, fmt.Errorf("timeout_ms must be positive")
		}
		cfg.Timeout = time.Duration(ms) * time.Millisecond
	}

	return cfg, nil
}

func loadMapping(path string) (mappingSpec, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return mappingSpec{}, fmt.Errorf("cannot read mapping file: %w", err)
	}

	var m mappingSpec
	if err := json.Unmarshal(data, &m); err != nil {
		return mappingSpec{}, fmt.Errorf("cannot parse mapping file: %w", err)
	}

	if len(m.Input) == 0 || len(m.Output) == 0 {
		return mappingSpec{}, fmt.Errorf("mapping must contain input and output")
	}

	for _, key := range inputFields {
		if strings.TrimSpace(m.Input[key]) == "" {
			return mappingSpec{}, fmt.Errorf("mapping.input.%s is required", key)
		}
	}
	for _, key := range outputFields {
		if strings.TrimSpace(m.Output[key]) == "" {
			return mappingSpec{}, fmt.Errorf("mapping.output.%s is required", key)
		}
	}

	return m, nil
}

func handleSOAPRequest(
	w http.ResponseWriter,
	req *http.Request,
	client *http.Client,
	cfg pluginConfig,
	mapping mappingSpec,
	gqlQuery string,
) {
	traceID := extractTraceID(req.Header)
	if traceID != "" {
		w.Header().Set("X-Trace-Id", traceID)
	}

	soapBody, err := io.ReadAll(io.LimitReader(req.Body, 1<<20))
	if err != nil {
		writeSOAPFault(w, http.StatusBadRequest, "не удалось прочитать SOAP тело", traceID)
		return
	}
	if len(bytes.TrimSpace(soapBody)) == 0 {
		writeSOAPFault(w, http.StatusBadRequest, "SOAP тело пустое", traceID)
		return
	}

	input, err := parseSOAPInput(soapBody)
	if err != nil {
		writeSOAPFault(w, http.StatusBadRequest, "некорректный SOAP запрос: "+err.Error(), traceID)
		return
	}

	variables, err := buildVariables(input, mapping)
	if err != nil {
		writeSOAPFault(w, http.StatusBadRequest, "ошибка маппинга входа: "+err.Error(), traceID)
		return
	}

	gqlPayload, err := json.Marshal(map[string]interface{}{
		"query":     gqlQuery,
		"variables": variables,
	})
	if err != nil {
		writeSOAPFault(w, http.StatusInternalServerError, "ошибка сборки GraphQL запроса", traceID)
		return
	}

	gqlRespBody, gqlStatus, err := callGraphQL(req.Context(), client, cfg.GraphQLURL, gqlPayload, req.Header)
	if err != nil {
		writeSOAPFault(w, http.StatusInternalServerError, "ошибка вызова GraphQL: "+err.Error(), traceID)
		return
	}
	if gqlStatus < 200 || gqlStatus >= 300 {
		writeSOAPFault(w, http.StatusInternalServerError, fmt.Sprintf("GraphQL вернул HTTP %d", gqlStatus), traceID)
		return
	}

	soapFields, err := mapGraphQLToSOAP(gqlRespBody, mapping)
	if err != nil {
		writeSOAPFault(w, http.StatusInternalServerError, err.Error(), traceID)
		return
	}

	if traceID != "" {
		logger.Info(fmt.Sprintf("[soap-graphql-plugin] clientId=%d requestId=%s trace_id=%s", input.ClientID, input.RequestID, traceID))
	}

	result := buildSOAPResponse(soapFields)
	w.Header().Set("Content-Type", soapContentType)
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(result))
}

func parseSOAPInput(raw []byte) (soapInput, error) {
	decoder := xml.NewDecoder(bytes.NewReader(raw))
	values := map[string]string{}
	insideRequest := false

	for {
		tok, err := decoder.Token()
		if err == io.EOF {
			break
		}
		if err != nil {
			return soapInput{}, err
		}

		switch t := tok.(type) {
		case xml.StartElement:
			local := strings.ToLower(t.Name.Local)
			if local == "getcxrequest" {
				insideRequest = true
				continue
			}
			if !insideRequest && !isInputField(local) {
				continue
			}
			if isInputField(local) {
				var value string
				if err := decoder.DecodeElement(&value, &t); err != nil {
					return soapInput{}, err
				}
				values[local] = strings.TrimSpace(value)
			}
		case xml.EndElement:
			if strings.EqualFold(t.Name.Local, "GetCxRequest") {
				insideRequest = false
			}
		}
	}

	for _, f := range inputFields {
		if strings.TrimSpace(values[strings.ToLower(f)]) == "" {
			return soapInput{}, fmt.Errorf("отсутствует поле %s", f)
		}
	}

	clientID, err := strconv.Atoi(values["clientid"])
	if err != nil {
		return soapInput{}, fmt.Errorf("clientId должен быть целым числом")
	}

	return soapInput{
		ClientID:  clientID,
		FirstName: values["firstname"],
		LastName:  values["lastname"],
		RequestID: values["requestid"],
	}, nil
}

func buildVariables(input soapInput, mapping mappingSpec) (map[string]interface{}, error) {
	source := map[string]interface{}{
		"clientId":  input.ClientID,
		"firstName": input.FirstName,
		"lastName":  input.LastName,
		"requestId": input.RequestID,
	}

	variables := map[string]interface{}{}
	for soapField, target := range mapping.Input {
		if !strings.HasPrefix(target, "variables.") {
			continue
		}
		varName := strings.TrimPrefix(target, "variables.")
		value, ok := source[soapField]
		if !ok {
			return nil, fmt.Errorf("неизвестное SOAP поле %s", soapField)
		}
		variables[varName] = value
	}

	for _, name := range inputFields {
		if _, ok := variables[name]; !ok {
			return nil, fmt.Errorf("не заполнена переменная %s", name)
		}
	}
	return variables, nil
}

func callGraphQL(
	ctx context.Context,
	client *http.Client,
	url string,
	payload []byte,
	incomingHeaders http.Header,
) ([]byte, int, error) {
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(payload))
	if err != nil {
		return nil, 0, err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	propagateTraceHeaders(httpReq.Header, incomingHeaders)

	resp, err := client.Do(httpReq)
	if err != nil {
		return nil, 0, err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(io.LimitReader(resp.Body, 2<<20))
	if err != nil {
		return nil, resp.StatusCode, err
	}

	return body, resp.StatusCode, nil
}

func mapGraphQLToSOAP(gqlPayload []byte, mapping mappingSpec) (map[string]string, error) {
	var gqlResp graphQLResponse
	if err := json.Unmarshal(gqlPayload, &gqlResp); err != nil {
		return nil, fmt.Errorf("некорректный JSON ответ GraphQL")
	}

	if len(gqlResp.Errors) > 0 {
		msg := strings.TrimSpace(gqlResp.Errors[0].Message)
		if msg == "" {
			msg = "GraphQL вернул ошибку"
		}
		return nil, fmt.Errorf("GraphQL error: %s", msg)
	}

	if gqlResp.Data == nil {
		return nil, fmt.Errorf("GraphQL вернул data=null")
	}

	source := map[string]interface{}{"data": gqlResp.Data}
	result := map[string]string{}
	for soapField, gqlPath := range mapping.Output {
		value, ok := pathValue(source, gqlPath)
		if !ok {
			result[soapField] = ""
			continue
		}
		result[soapField] = normalizeValue(value)
	}

	for _, key := range outputFields {
		if _, ok := result[key]; !ok {
			result[key] = ""
		}
	}

	return result, nil
}

func pathValue(root map[string]interface{}, path string) (interface{}, bool) {
	parts := strings.Split(path, ".")
	var current interface{} = root

	for _, part := range parts {
		node, ok := current.(map[string]interface{})
		if !ok {
			return nil, false
		}
		next, ok := node[part]
		if !ok {
			return nil, false
		}
		current = next
	}
	return current, true
}

func normalizeValue(v interface{}) string {
	switch t := v.(type) {
	case nil:
		return ""
	case string:
		return t
	case float64:
		if math.Mod(t, 1.0) == 0 {
			return strconv.FormatInt(int64(t), 10)
		}
		return strconv.FormatFloat(t, 'f', -1, 64)
	case bool:
		return strconv.FormatBool(t)
	default:
		return fmt.Sprintf("%v", t)
	}
}

func buildSOAPResponse(fields map[string]string) string {
	var b strings.Builder
	b.WriteString("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n")
	b.WriteString(fmt.Sprintf("<soapenv:Envelope xmlns:soapenv=\"%s\" xmlns:cx=\"%s\">\n", soapEnvNS, soapCxNS))
	b.WriteString("  <soapenv:Body>\n")
	b.WriteString("    <cx:GetCxResponse>\n")

	for _, field := range outputFields {
		b.WriteString(fmt.Sprintf("      <cx:%s>%s</cx:%s>\n", field, escapeXML(fields[field]), field))
	}

	b.WriteString("    </cx:GetCxResponse>\n")
	b.WriteString("  </soapenv:Body>\n")
	b.WriteString("</soapenv:Envelope>\n")
	return b.String()
}

func writeSOAPFault(w http.ResponseWriter, status int, message string, traceID string) {
	fault := buildSOAPFault(message)
	w.Header().Set("Content-Type", soapContentType)
	if traceID != "" {
		w.Header().Set("X-Trace-Id", traceID)
	}
	w.WriteHeader(status)
	_, _ = w.Write([]byte(fault))
}

func buildSOAPFault(message string) string {
	var b strings.Builder
	b.WriteString("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n")
	b.WriteString(fmt.Sprintf("<soapenv:Envelope xmlns:soapenv=\"%s\" xmlns:cx=\"%s\">\n", soapEnvNS, soapCxNS))
	b.WriteString("  <soapenv:Body>\n")
	b.WriteString("    <soapenv:Fault>\n")
	b.WriteString("      <faultcode>soapenv:Server</faultcode>\n")
	b.WriteString(fmt.Sprintf("      <faultstring>%s</faultstring>\n", escapeXML(message)))
	b.WriteString("    </soapenv:Fault>\n")
	b.WriteString("  </soapenv:Body>\n")
	b.WriteString("</soapenv:Envelope>\n")
	return b.String()
}

func propagateTraceHeaders(dst http.Header, src http.Header) {
	for _, key := range []string{"traceparent", "tracestate", "baggage"} {
		value := strings.TrimSpace(src.Get(key))
		if value != "" {
			dst.Set(key, value)
		}
	}

	traceID := extractTraceID(src)
	if traceID != "" {
		dst.Set("X-Trace-Id", traceID)
	}
}

func extractTraceID(headers http.Header) string {
	if custom := strings.TrimSpace(headers.Get("X-Trace-Id")); custom != "" {
		return custom
	}

	traceparent := strings.TrimSpace(headers.Get("traceparent"))
	if traceparent == "" {
		return ""
	}

	parts := strings.Split(traceparent, "-")
	if len(parts) < 4 {
		return ""
	}

	traceID := strings.ToLower(strings.TrimSpace(parts[1]))
	if len(traceID) != 32 {
		return ""
	}

	return traceID
}

func escapeXML(value string) string {
	var b bytes.Buffer
	if err := xml.EscapeText(&b, []byte(value)); err != nil {
		return ""
	}
	return b.String()
}

func isInputField(local string) bool {
	switch local {
	case "clientid", "firstname", "lastname", "requestid":
		return true
	default:
		return false
	}
}

func toInt(v interface{}) (int, error) {
	switch t := v.(type) {
	case int:
		return t, nil
	case float64:
		return int(t), nil
	case string:
		return strconv.Atoi(strings.TrimSpace(t))
	default:
		return 0, fmt.Errorf("unsupported type %T", v)
	}
}

func buildGraphQLQuery() string {
	return `query GetCxData($clientId:Int!,$firstName:String!,$lastName:String!,$requestId:String!){
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
}`
}
