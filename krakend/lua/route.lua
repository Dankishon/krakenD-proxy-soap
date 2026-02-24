-- Инициализация генератора случайных чисел на основе текущего времени
-- Это нужно для генерации уникальных trace_id в каждом запросе
math.randomseed(os.time())

-- Функция извлечения значения параметра из query string
-- Параметры:
--   raw_query - строка запроса (например, "?clientId=1&op=echo" или "clientId=1")
--   key - имя параметра для извлечения (например, "clientId")
-- Возвращает: значение параметра или nil, если параметр не найден
local function extract_query_param(raw_query, key)
    -- Проверка: если query string пустая или nil, возвращаем nil
    if raw_query == nil or raw_query == "" then
        return nil
    end

    -- Попытка 1: ищем параметр в формате "?key=value" или "&key=value"
    -- Регулярное выражение: [?&] - начало с ? или &, затем key=, затем значение до & или конца строки
    -- [^&]+ означает "один или более символов, кроме &"
    local value = string.match(raw_query, "[?&]" .. key .. "=([^&]+)")
    
    -- Попытка 2: если не нашли, пробуем формат "key=value" в начале строки
    -- ^ означает начало строки
    if value == nil then
        value = string.match(raw_query, "^" .. key .. "=([^&]+)")
    end
    
    -- Попытка 3: последняя попытка - ищем "key=value" в любом месте строки
    if value == nil then
        value = string.match(raw_query, key .. "=([^&]+)")
    end

    -- Финальная проверка: если значение пустое или nil, возвращаем nil
    if value == nil or value == "" then
        return nil
    end

    -- Возвращаем найденное значение
    return value
end

-- Функция формирования ответа с ошибкой 400 Bad Request
-- Параметры:
--   resp - объект response из KrakenD для установки заголовков и тела ответа
--   message - текст сообщения об ошибке
local function write_bad_request(resp, message)
    -- Устанавливаем HTTP статус код 400 (Bad Request)
    resp:statusCode(400)
    
    -- Устанавливаем Content-Type как plain text с UTF-8 кодировкой
    resp:headers("Content-Type", "text/plain; charset=utf-8")
    
    -- Устанавливаем длину контента в байтах (tostring конвертирует число в строку)
    resp:headers("Content-Length", tostring(string.len(message)))
    
    -- Устанавливаем тело ответа с сообщением об ошибке
    resp:body(message)
    
    -- Помечаем ответ как завершенный (KrakenD не будет обращаться к бэкендам)
    resp:isComplete(true)
end

-- Основная функция вычисления решения о маршрутизации
-- Параметры:
--   req - объект request из KrakenD для доступа к query параметрам
-- Возвращает: таблицу с решением или nil, error_message в случае ошибки
local function compute_decision(req)
    -- Получаем полную строку query параметров из запроса
    -- Например: "?clientId=1&op=echo" или "clientId=1"
    local raw_query = req:query()
    
    -- Извлекаем значение параметра clientId из query string
    local client_id_raw = extract_query_param(raw_query, "clientId")
    
    -- Извлекаем значение параметра op из query string (опциональный параметр)
    local op_raw = extract_query_param(raw_query, "op")

    -- Валидация: clientId обязателен для маршрутизации
    if client_id_raw == nil then
        -- Возвращаем nil и сообщение об ошибке
        return nil, "clientId is required"
    end

    -- Валидация: clientId должен быть целым числом (может быть отрицательным)
    -- Регулярное выражение: ^-?%d+$
    --   ^ - начало строки
    --   -? - опциональный знак минус
    --   %d+ - одна или более цифр
    --   $ - конец строки
    if string.match(client_id_raw, "^-?%d+$") == nil then
        return nil, "clientId must be integer"
    end

    -- Конвертируем строку clientId в число для дальнейших вычислений
    local client_id = tonumber(client_id_raw)
    
    -- Определяем целевой сервис по умолчанию (сервис B)
    local target = "b"
    
    -- Логика маршрутизации: если clientId от 1 до 6 включительно, используем сервис C
    -- Иначе остается сервис B (по умолчанию)
    if client_id >= 1 and client_id <= 6 then
        target = "c"
    end

    -- Определяем операцию: по умолчанию "hello", если передан op=echo, то "echo"
    local op = "hello"
    if op_raw == "echo" then
        op = "echo"
    end

    -- Генерируем уникальный trace_id для отслеживания запроса
    -- Формат: timestamp-случайное_число_от_1000_до_9999
    -- Например: "1234567890-5678"
    local trace_id = tostring(os.time()) .. "-" .. tostring(math.random(1000, 9999))
    
    -- Формируем URL для редиректа/маршрутизации
    -- Формат: /api/{target}/hello?clientId={clientId}&traceId={traceId}
    -- Например: "/api/c/hello?clientId=1&traceId=1234567890-5678"
    local routed_url = "/api/" .. target .. "/hello?clientId=" .. client_id_raw .. "&traceId=" .. trace_id

    -- Возвращаем таблицу с решением и nil в качестве ошибки (успех)
    return {
        client_id = client_id,           -- Числовое значение clientId
        client_id_raw = client_id_raw,   -- Строковое значение clientId (для URL)
        op = op,                         -- Операция (hello или echo)
        target = target,                 -- Целевой сервис (b или c)
        trace_id = trace_id,             -- Уникальный ID для трассировки
        routed_url = routed_url,         -- Сформированный URL для маршрутизации
    }, nil
end

-- Публичная функция-обертка для обратной совместимости
-- Вызывает основную функцию route_decision_json
-- Параметры:
--   req - объект request из KrakenD
--   resp - объект response из KrakenD
function route_decision(req, resp)
    route_decision_json(req, resp)
end

-- Основная публичная функция, вызываемая KrakenD в фазе post
-- Эта функция выполняется после запроса к бэкенду и может модифицировать ответ
-- Параметры:
--   req - объект request из KrakenD (для доступа к query параметрам)
--   resp - объект response из KrakenD (для установки статуса, заголовков и тела)
function route_decision_json(req, resp)
    -- Вызываем функцию вычисления решения о маршрутизации
    -- decision - таблица с решением или nil в случае ошибки
    -- err - сообщение об ошибке или nil при успехе
    local decision, err = compute_decision(req)
    
    -- Если решение не получено (ошибка валидации), отправляем ответ с ошибкой
    if decision == nil then
        write_bad_request(resp, err)
        return  -- Прерываем выполнение функции
    end

    -- Формируем JSON тело ответа с информацией о маршрутизации
    -- string.format форматирует строку, подставляя значения из таблицы decision
    -- %s - плейсхолдер для строки
    local body = string.format(
        '{"service":"%s","url":"%s"}',
        decision.target,      -- Целевой сервис (b или c)
        decision.routed_url  -- URL для маршрутизации
    )

    -- Устанавливаем HTTP статус код 200 (OK) - успешный ответ
    resp:statusCode(200)
    
    -- Устанавливаем Content-Type как JSON
    resp:headers("Content-Type", "application/json")
    
    -- Добавляем кастомный заголовок с trace_id для трассировки запроса
    resp:headers("X-Trace-Id", decision.trace_id)
    
    -- Добавляем кастомный заголовок с информацией о целевом сервисе
    resp:headers("X-Routed-To", decision.target)
    
    -- Устанавливаем длину контента в байтах
    resp:headers("Content-Length", tostring(string.len(body)))
    
    -- Устанавливаем тело ответа (JSON строка)
    resp:body(body)
    
    -- Помечаем ответ как завершенный (KrakenD не будет обрабатывать ответ от бэкенда)
    resp:isComplete(true)
end
