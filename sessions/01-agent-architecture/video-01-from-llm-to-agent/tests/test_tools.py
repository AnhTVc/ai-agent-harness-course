"""Tool contracts, safe arithmetic, and bounded weather API behavior."""

import json
import unittest
from unittest.mock import MagicMock, patch

from agent_lab.tools import TOOL_SCHEMAS, execute, validate_tool_arguments


class ToolSchemaTests(unittest.TestCase):
    """Keep model-visible descriptions aligned with trusted executors."""

    def test_every_registered_tool_has_a_closed_one_argument_contract(self):
        names = {schema["function"]["name"] for schema in TOOL_SCHEMAS}
        self.assertEqual(names, {"search_documents", "search_weather", "calculate"})
        for schema in TOOL_SCHEMAS:
            function = schema["function"]
            parameters = function["parameters"]
            self.assertEqual(parameters["required"], list(parameters["properties"]))
            self.assertFalse(parameters["additionalProperties"])
            self.assertGreaterEqual(len(function["description"]), 20)

    def test_weather_input_validation_rejects_urls_and_control_characters(self):
        for arguments in (
            {"location": " "},
            {"location": "https://example.com"},
            {"location": "Hanoi\nsecond line"},
            {"location": "x" * 101},
            {"location": "Hanoi", "url": "https://example.com"},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                validate_tool_arguments("search_weather", arguments)

    def test_calculator_rejects_code_and_oversized_expressions(self):
        for arguments in (
            {"expression": "__import__('os').system('whoami')"},
            {"expression": "1 / 0"},
            {"expression": "2 ** 1000000000"},
            {"expression": "x" * 201},
            {"expression": "1", "url": "https://example.com"},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                validate_tool_arguments("calculate", arguments)

    def test_calculator_supports_bounded_arithmetic_without_eval(self):
        self.assertEqual(
            execute("calculate", {"expression": "1847 * (23 + 19) / 7"})["result"],
            11082,
        )


class WeatherToolTests(unittest.TestCase):
    """Mock network responses while checking fixed HTTPS endpoints and limits."""

    @staticmethod
    def response(body):
        """Create a context-manager response matching urllib's small interface."""
        result = MagicMock()
        result.__enter__.return_value.read.return_value = json.dumps(body).encode()
        result.__exit__.return_value = False
        return result

    @patch("agent_lab.tools.urlopen")
    def test_weather_resolves_city_then_requests_current_conditions(self, open_url):
        open_url.side_effect = [
            self.response(
                {
                    "results": [
                        {
                            "name": "Hanoi",
                            "country": "Vietnam",
                            "admin1": "Hanoi",
                            "latitude": 21.0285,
                            "longitude": 105.8542,
                        }
                    ]
                }
            ),
            self.response(
                {
                    "current": {
                        "time": "2026-10-20T14:00",
                        "temperature_2m": 27.5,
                        "relative_humidity_2m": 71,
                        "apparent_temperature": 30.1,
                        "is_day": 1,
                        "precipitation": 0.0,
                        "weather_code": 2,
                        "wind_speed_10m": 8.4,
                    },
                    "current_units": {
                        "temperature_2m": "°C",
                        "relative_humidity_2m": "%",
                        "apparent_temperature": "°C",
                        "precipitation": "mm",
                        "wind_speed_10m": "km/h",
                    },
                }
            ),
        ]

        result = execute("search_weather", {"location": "Hanoi, Vietnam"})

        self.assertEqual(result["tool"], "search_weather")
        self.assertEqual(result["matched_location"]["name"], "Hanoi")
        self.assertEqual(result["condition"], "Partly cloudy")
        self.assertEqual(result["current"]["temperature"], 27.5)
        self.assertEqual(result["source"], "Open-Meteo")
        geo_request = open_url.call_args_list[0].args[0]
        forecast_request = open_url.call_args_list[1].args[0]
        self.assertEqual(
            geo_request.full_url.split("/")[2], "geocoding-api.open-meteo.com"
        )
        self.assertEqual(forecast_request.full_url.split("/")[2], "api.open-meteo.com")
        self.assertTrue(forecast_request.full_url.startswith("https://"))
        self.assertEqual(open_url.call_args_list[0].kwargs["timeout"], 8)
        self.assertEqual(open_url.call_args_list[1].kwargs["timeout"], 8)

    @patch("agent_lab.tools.urlopen")
    def test_weather_returns_a_clear_error_for_unknown_city(self, open_url):
        open_url.return_value = self.response({"results": []})
        with self.assertRaisesRegex(ValueError, "No matching location"):
            execute("search_weather", {"location": "No Such Place 82736"})
        open_url.assert_called_once()

    @patch("agent_lab.tools.urlopen", side_effect=TimeoutError)
    def test_weather_does_not_leak_network_exception_details(self, _open_url):
        with self.assertRaisesRegex(ValueError, "Weather provider request failed"):
            execute("search_weather", {"location": "Hanoi"})

    @patch("agent_lab.tools.urlopen")
    def test_weather_rejects_untrusted_out_of_range_provider_data(self, open_url):
        open_url.return_value = self.response(
            {
                "results": [
                    {
                        "name": "Hanoi",
                        "country": "Vietnam",
                        "latitude": 10**1000,
                        "longitude": 105.8,
                    }
                ]
            }
        )
        with self.assertRaisesRegex(ValueError, "invalid location data"):
            execute("search_weather", {"location": "Hanoi"})
        open_url.assert_called_once()


if __name__ == "__main__":
    unittest.main()
