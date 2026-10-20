"""Allowlisted tools for the lesson's inspectable execution loop.

Schemas are model-facing descriptions only. ``execute`` remains the single
trusted dispatch point for the synthetic document fixture, bounded arithmetic,
and fixed-host Open-Meteo requests.
"""

import ast
import json
import math
import operator
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from .network import verified_https_context


# Synthetic, read-only records keep the document tool deterministic in class.
DOCUMENTS = (
    {
        "id": "DOC-001",
        "title": "Company AI overview",
        "text": "ExampleCo provides document assistants, AI agent prototypes, and evaluation services. This is synthetic course data, not an R&D Technology capability claim.",
        "keywords": ["company", "capability", "capabilities", "overview", "services"],
    },
    {
        "id": "DOC-002",
        "title": "AI agent delivery",
        "text": "ExampleCo prototypes agents with explicit tool contracts, a runtime-controlled execution loop, and inspectable traces.",
        "keywords": ["agent", "agents", "tool", "tools", "architecture"],
    },
    {
        "id": "DOC-003",
        "title": "Document assistants",
        "text": "ExampleCo document assistants retrieve source passages and include document IDs so readers can check their answers.",
        "keywords": [
            "rag",
            "retrieval",
            "document",
            "documents",
            "assistant",
            "assistants",
        ],
    },
    {
        "id": "DOC-004",
        "title": "Evaluation services",
        "text": "ExampleCo checks tool execution with deterministic tests and evaluates answer quality separately using a documented rubric.",
        "keywords": ["evaluation", "eval", "testing", "quality", "tests"],
    },
)


# Model-facing contracts are closed, single-argument capabilities. Describing
# a tool here never imports or exposes its implementation to the model.
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "Search synthetic course documents by topic. Returns source IDs and text, or an empty list. Read only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 2000,
                        "description": "The document topic to look up, such as AI agents or evaluation.",
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_weather",
            "description": "Resolve a place name and retrieve its current weather from the fixed Open-Meteo API. Read only; the location must be a place name, never a URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 100,
                        "description": "A city or place name, such as Hanoi, Vietnam.",
                    }
                },
                "required": ["location"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate a short arithmetic expression using bounded numeric operations. No names, functions, or code execution are allowed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200,
                        "description": "Arithmetic using numbers, parentheses, +, -, *, /, //, and %, such as 12 * (3 + 4).",
                    }
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
        },
    },
]

# Keep the original lesson exercise stable while the runtime exposes all tools.
TOOL_SCHEMA = TOOL_SCHEMAS[0]

_ARGUMENT_KEYS = {
    "search_documents": "query",
    "search_weather": "location",
    "calculate": "expression",
}
_WEATHER_TIMEOUT_SECONDS = 8
_WEATHER_RESPONSE_LIMIT_BYTES = 256_000
_MAX_EXPRESSION_NODES = 40
_MAX_NUMBER = 1_000_000_000_000
_ARITHMETIC_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def check_schema(schema):
    """Check the exact search schema exercise, not arbitrary JSON Schema.

    Students supply a schema here; the trusted runtime always uses registered
    contracts in ``TOOL_SCHEMAS``. Editing text cannot register an executor.
    """
    errors = []
    if not isinstance(schema, dict):
        return ["Schema must be a JSON object."]
    fn = schema.get("function")
    if schema.get("type") != "function" or not isinstance(fn, dict):
        return ["Use type=function and a function object."]
    if fn.get("name") != "search_documents":
        errors.append(
            "Function name must match the registered search_documents executor."
        )
    if (
        not isinstance(fn.get("description"), str)
        or len(fn["description"].strip()) < 20
    ):
        errors.append(
            "Explain capability, read-only behavior, and the empty-result case."
        )
    params = fn.get("parameters", {})
    if not isinstance(params, dict):
        return errors + ["Parameters must be an object."]
    props = params.get("properties", {})
    query = props.get("query", {}) if isinstance(props, dict) else {}
    if (
        params.get("type") != "object"
        or not isinstance(query, dict)
        or query.get("type") != "string"
    ):
        errors.append("Parameters must define query as a string property.")
    if params.get("required") != ["query"]:
        errors.append("The query parameter must be required.")
    if params.get("additionalProperties") is not False:
        errors.append("Reject unexpected arguments with additionalProperties=false.")
    if isinstance(query, dict) and (
        query.get("minLength") != 1 or query.get("maxLength") != 2000
    ):
        errors.append(
            "Set query minLength=1 and maxLength=2000 to match runtime validation."
        )
    return errors


def _bounded_number(value):
    """Reject booleans, non-finite numbers, and arithmetic outside demo bounds."""
    if type(value) not in (int, float):
        raise ValueError("Only numeric arithmetic is allowed.")
    try:
        finite = math.isfinite(value)
    except (OverflowError, TypeError):
        finite = False
    if not finite or abs(value) > _MAX_NUMBER:
        raise ValueError("Arithmetic result must be finite and within the demo range.")
    return value


def _evaluate_arithmetic(node):
    """Evaluate only numeric literals and an explicit arithmetic AST whitelist."""
    if isinstance(node, ast.Constant):
        return _bounded_number(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate_arithmetic(node.operand)
        return _bounded_number(value if isinstance(node.op, ast.UAdd) else -value)
    if isinstance(node, ast.BinOp) and type(node.op) in _ARITHMETIC_OPERATORS:
        left = _evaluate_arithmetic(node.left)
        right = _evaluate_arithmetic(node.right)
        try:
            value = _ARITHMETIC_OPERATORS[type(node.op)](left, right)
        except (ArithmeticError, OverflowError) as exc:
            raise ValueError("Arithmetic expression is undefined.") from exc
        return _bounded_number(value)
    raise ValueError("Expression contains an unsupported operation.")


def _calculate(expression):
    """Parse a small arithmetic expression without calling eval or exec."""
    if not isinstance(expression, str) or not 1 <= len(expression.strip()) <= 200:
        raise ValueError("Expression must contain 1 to 200 characters.")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError("Expression must contain valid arithmetic.") from exc
    if sum(1 for _ in ast.walk(tree)) > _MAX_EXPRESSION_NODES:
        raise ValueError("Expression contains too many operations.")
    result = _evaluate_arithmetic(tree.body)
    # Use JSON-friendly integers for whole-number divisions and bounded decimal output.
    if isinstance(result, float) and result.is_integer():
        return int(result)
    return round(result, 8) if isinstance(result, float) else result


def validate_tool_arguments(name, arguments):
    """Apply the same closed argument contract before dispatch and debug edits."""
    expected_key = _ARGUMENT_KEYS.get(name)
    if expected_key is None:
        raise ValueError("Tool is not registered.")
    if not isinstance(arguments, dict) or set(arguments) != {expected_key}:
        raise ValueError(f"Expected exactly one {expected_key} argument.")
    value = arguments[expected_key]
    if name == "search_documents":
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 2000:
            raise ValueError("Query must contain 1 to 2000 characters.")
        value = value.strip()
    elif name == "search_weather":
        if (
            not isinstance(value, str)
            or not 1 <= len(value.strip()) <= 100
            or "://" in value
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError(
                "Location must be a place name of 1 to 100 characters, not a URL."
            )
        value = value.strip()
    else:
        _calculate(value)
        value = value.strip()
    return {expected_key: value}


def _open_meteo_json(url):
    """Fetch one fixed-host API response with a short timeout and size bound."""
    request = Request(url, headers={"User-Agent": "AgentRuntimeDebugger/1.0"})
    # The URL is assembled only from fixed hosts and encoded query parameters.
    with urlopen(
        request, timeout=_WEATHER_TIMEOUT_SECONDS, context=verified_https_context()
    ) as response:
        payload = response.read(_WEATHER_RESPONSE_LIMIT_BYTES + 1)
    if len(payload) > _WEATHER_RESPONSE_LIMIT_BYTES:
        raise ValueError("Weather provider response exceeded the size limit.")
    return json.loads(payload)


def _weather_number(record, key, minimum, maximum):
    """Validate untrusted weather values before placing them in model context."""
    value = record.get(key)
    if (
        type(value) not in (int, float)
        or not _is_finite_number(value)
        or not minimum <= value <= maximum
    ):
        raise ValueError("Weather provider returned invalid current conditions.")
    return value


def _is_finite_number(value):
    """Handle oversized JSON integers without allowing a conversion exception."""
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError):
        return False


def _weather_unit(units, key):
    """Keep provider-supplied unit labels short and text-only."""
    value = units.get(key)
    if not isinstance(value, str) or not 1 <= len(value) <= 20:
        raise ValueError("Weather provider returned invalid units.")
    return value


def _search_weather(location):
    """Resolve a place name, then request a compact current-conditions record."""
    geocoding_url = "https://geocoding-api.open-meteo.com/v1/search?" + urlencode(
        {"name": location, "count": 1, "language": "en", "format": "json"}
    )
    try:
        geocoding = _open_meteo_json(geocoding_url)
    except Exception as exc:
        raise ValueError(
            "Weather provider request failed during location lookup."
        ) from exc
    locations = geocoding.get("results") if isinstance(geocoding, dict) else None
    if not isinstance(locations, list) or not locations:
        raise ValueError("No matching location was found.")
    place = locations[0]
    if not isinstance(place, dict):
        raise ValueError("Weather provider returned invalid location data.")
    latitude, longitude = place.get("latitude"), place.get("longitude")
    if (
        type(latitude) not in (int, float)
        or type(longitude) not in (int, float)
        or not _is_finite_number(latitude)
        or not _is_finite_number(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise ValueError("Weather provider returned invalid location data.")
    if not isinstance(place.get("name"), str) or not 1 <= len(place["name"]) <= 120:
        raise ValueError("Weather provider returned invalid location data.")

    forecast_url = "https://api.open-meteo.com/v1/forecast?" + urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m",
            "timezone": "auto",
            "forecast_days": 1,
        }
    )
    try:
        forecast = _open_meteo_json(forecast_url)
    except Exception as exc:
        raise ValueError(
            "Weather provider request failed during forecast lookup."
        ) from exc
    current = forecast.get("current") if isinstance(forecast, dict) else None
    units = forecast.get("current_units", {}) if isinstance(forecast, dict) else {}
    if not isinstance(current, dict) or not isinstance(units, dict):
        raise ValueError("Weather provider returned invalid current conditions.")
    weather_code = current.get("weather_code")
    observed_at = current.get("time")
    is_day = current.get("is_day")
    if (
        type(weather_code) is not int
        or not isinstance(observed_at, str)
        or not 1 <= len(observed_at) <= 50
        or type(is_day) is not int
        or is_day not in (0, 1)
    ):
        raise ValueError("Weather provider returned an invalid weather code.")
    temperature = _weather_number(current, "temperature_2m", -100, 80)
    feels_like = _weather_number(current, "apparent_temperature", -100, 80)
    humidity = _weather_number(current, "relative_humidity_2m", 0, 100)
    precipitation = _weather_number(current, "precipitation", 0, 1000)
    wind_speed = _weather_number(current, "wind_speed_10m", 0, 500)
    temperature_unit = _weather_unit(units, "temperature_2m")
    humidity_unit = _weather_unit(units, "relative_humidity_2m")
    precipitation_unit = _weather_unit(units, "precipitation")
    wind_speed_unit = _weather_unit(units, "wind_speed_10m")

    # Keep the observation compact so the agent context shows only useful facts.
    return {
        "tool": "search_weather",
        "matched_location": {
            key: place[key][:120]
            for key in ("name", "admin1", "country")
            if isinstance(place.get(key), str) and place[key]
        },
        "observed_at": observed_at,
        "condition": _WEATHER_CODES.get(weather_code, "Unknown condition"),
        "current": {
            "temperature": temperature,
            "temperature_unit": temperature_unit,
            "feels_like": feels_like,
            "relative_humidity": humidity,
            "humidity_unit": humidity_unit,
            "precipitation": precipitation,
            "precipitation_unit": precipitation_unit,
            "wind_speed": wind_speed,
            "wind_speed_unit": wind_speed_unit,
            "is_day": is_day,
        },
        "source": "Open-Meteo",
    }


def execute(name, arguments):
    """Validate the allowlist and arguments before consulting any environment."""
    arguments = validate_tool_arguments(name, arguments)
    if name == "search_documents":
        return _search_documents(arguments["query"])
    if name == "calculate":
        expression = arguments["expression"]
        return {
            "tool": name,
            "expression": expression,
            "result": _calculate(expression),
        }
    return _search_weather(arguments["location"])


def _search_documents(query):
    """Search only the read-only classroom fixture and retain source IDs."""
    words = set(re.findall(r"[a-z]+", query.lower()))
    return {
        "tool": "search_documents",
        "matches": [
            {key: passage[key] for key in ("id", "title", "text")}
            for passage in DOCUMENTS
            if words.intersection(passage["keywords"])
        ],
        "source": "synthetic-classroom-fixture",
    }


def tool_implementation(name):
    """Return the registered handler used to point the debugger at real source."""
    implementations = {
        "search_documents": _search_documents,
        "search_weather": _search_weather,
        "calculate": _calculate,
    }
    if name not in implementations:
        raise ValueError("Tool is not registered.")
    return implementations[name]
