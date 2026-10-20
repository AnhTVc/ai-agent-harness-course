"""Behavior contracts for the lesson. Provider fakes do not prove LLM quality."""

import copy
import json
import os
import ssl
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from agent_lab.runtime import Execution, run
from agent_lab.providers import CloudflareModel, OllamaModel, OfflineModel
from agent_lab.config import load_env_file
from agent_lab.tools import execute, TOOL_SCHEMA, TOOL_SCHEMAS, check_schema


class RuntimeTests(unittest.TestCase):
    """Test boundary evidence, errors, and stop conditions in isolated runs."""

    def test_agent_feeds_evidence_back_to_model(self):
        result = run("Summarize the company AI capabilities.")
        self.assertEqual(result["status"], "completed")
        self.assertIn("DOC-001", result["answer"])
        kinds = [event["kind"] for event in result["events"]]
        self.assertLess(kinds.index("tool_request"), kinds.index("tool_result"))
        self.assertLess(kinds.index("tool_result"), kinds.index("observation"))
        self.assertEqual(result["model_calls"], 2)
        self.assertEqual(result["tool_calls"], 1)
        self.assertEqual(result["provider"], "offline-rule-based")
        self.assertEqual(result["messages"][-2]["role"], "tool")
        self.assertEqual(result["events"][-1]["kind"], "stop")

    def test_model_can_answer_without_requesting_a_tool(self):
        result = run("Hello")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["model_calls"], 1)
        self.assertEqual(result["tool_calls"], 0)
        self.assertNotIn("tool_request", [event["kind"] for event in result["events"]])

    def test_runtime_exposes_each_allowlisted_tool_description(self):
        execution = Execution("Find the weather in Hanoi")
        while execution.next_action["kind"] != "model_input":
            execution.step()
        event = next(
            event
            for event in execution.result["events"]
            if event["kind"] == "tool_specs"
        )
        self.assertEqual(
            {tool["function"]["name"] for tool in event["payload"]["tools"]},
            {"search_documents", "search_weather", "calculate"},
        )

    def test_offline_model_selects_weather_and_calculation_tools(self):
        weather = OfflineModel().complete(
            [
                {
                    "role": "user",
                    "content": "What is the current weather in Hanoi, Vietnam?",
                }
            ],
            TOOL_SCHEMAS,
        )
        calculation = OfflineModel().complete(
            [{"role": "user", "content": "Calculate 1847 * (23 + 19) / 7"}],
            TOOL_SCHEMAS,
        )
        self.assertEqual(weather["tool_calls"][0]["function"]["name"], "search_weather")
        self.assertEqual(
            weather["tool_calls"][0]["function"]["arguments"],
            {"location": "Hanoi, Vietnam"},
        )
        self.assertEqual(calculation["tool_calls"][0]["function"]["name"], "calculate")
        self.assertEqual(
            calculation["tool_calls"][0]["function"]["arguments"],
            {"expression": "1847 * (23 + 19) / 7"},
        )

    def test_weather_observation_returns_to_the_next_model_call(self):
        weather = {
            "tool": "search_weather",
            "matched_location": {"name": "Hanoi", "country": "Vietnam"},
            "condition": "Partly cloudy",
            "observed_at": "2026-10-20T14:00",
            "current": {"temperature": 27.5, "temperature_unit": "°C"},
            "source": "Open-Meteo",
        }
        with patch("agent_lab.runtime.execute", return_value=weather) as execute_tool:
            result = run("What is the current weather in Hanoi, Vietnam?")
        execute_tool.assert_called_once_with(
            "search_weather", {"location": "Hanoi, Vietnam"}
        )
        self.assertEqual(result["tool_calls"], 1)
        self.assertEqual(result["messages"][-2]["tool_name"], "search_weather")
        self.assertIn("27.5", result["answer"])
        self.assertIn("Open-Meteo", result["answer"])

    def test_calculation_observation_is_summarized_from_tool_result(self):
        result = run("Calculate 1847 * (23 + 19) / 7")
        self.assertEqual(result["tool_calls"], 1)
        self.assertEqual(result["events"][-1]["kind"], "stop")
        self.assertIn("11082", result["answer"])

    def test_unknown_topic_does_not_invent_evidence(self):
        result = run("Find information about submarine manufacturing.")
        self.assertIn("No matching", result["answer"])
        self.assertNotIn("DOC-", result["answer"])

    def test_chatbot_has_no_tool_access(self):
        result = run("Summarize company capabilities", mode="chatbot")
        self.assertEqual(result["tool_calls"], 0)
        self.assertNotIn("DOC-001", result["answer"])

    def test_workflow_is_code_only(self):
        result = run("Summarize company capabilities", mode="workflow")
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(result["tool_calls"], 1)
        self.assertEqual(result["provider"], "code-only")
        self.assertIn("DOC-001", result["answer"])

    def test_missing_boundaries_are_visible(self):
        for fault in ("no_specs", "no_executor", "no_observation"):
            with self.subTest(fault=fault):
                result = run("Find company capabilities", fault=fault)
                self.assertTrue(
                    any(e["kind"] == "boundary_missing" for e in result["events"])
                )
                self.assertNotIn("DOC-001", result["answer"])

    def test_dropped_observations_stop_at_budget(self):
        result = run("Find company capabilities", fault="no_observation", max_steps=2)
        self.assertEqual(result["status"], "step_limit")
        self.assertEqual(result["model_calls"], 2)
        self.assertEqual(result["tool_calls"], 2)

    def test_model_limit_and_stop_are_separate_debugger_steps(self):
        execution = Execution("Find company capabilities", max_steps=1)
        while execution.next_action["kind"] != "call_model":
            execution.step()
        execution.step()
        execution.step()
        execution.step()
        execution.step()
        self.assertEqual(execution.next_action["kind"], "model_input")
        execution.step()
        self.assertFalse(execution.done)
        self.assertEqual(execution.result["events"][-1]["kind"], "step_limit")
        self.assertEqual(execution.next_action["kind"], "finalize")
        execution.step()
        self.assertTrue(execution.done)
        self.assertEqual(execution.result["events"][-1]["kind"], "stop")

    def test_missing_executor_rejection_and_stop_are_separate_steps(self):
        execution = Execution("Find company capabilities", fault="no_executor")
        while execution.next_action["kind"] != "execute_tool":
            execution.step()
        execution.step()
        self.assertFalse(execution.done)
        self.assertEqual(execution.result["events"][-1]["kind"], "tool_error")
        self.assertEqual(execution.next_action["kind"], "finalize")
        execution.step()
        self.assertTrue(execution.done)
        self.assertEqual(execution.result["events"][-1]["kind"], "stop")

    def test_validation_rejects_bad_inputs(self):
        for kwargs in (
            {"prompt": ""},
            {"prompt": "x" * 2001},
            {"prompt": 3},
            {"prompt": "x", "max_steps": True},
            {"prompt": "x", "max_steps": 7},
            {"prompt": "x", "mode": "shell"},
            {"prompt": "x", "fault": "unknown"},
            {"prompt": "x", "provider": "cloud"},
            {"prompt": "x", "mode": "chatbot", "fault": "no_specs"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                run(**kwargs)

    def test_allowlist_and_argument_validation(self):
        for name, args in [
            ("shell", {}),
            ("search_documents", {}),
            ("search_documents", {"query": 3}),
            ("search_documents", {"query": " "}),
            ("search_documents", {"query": "agents", "path": "/etc/passwd"}),
        ]:
            with self.subTest(name=name, args=args), self.assertRaises(ValueError):
                execute(name, args)

    def test_unregistered_tool_is_rejected_even_if_a_model_proposes_it(self):
        fake = MagicMock()
        fake.complete.side_effect = lambda messages, _tools: (
            {"role": "assistant", "content": "Rejected request observed."}
            if any(message["role"] == "tool" for message in messages)
            else {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "fetch_url",
                            "arguments": {"url": "https://example.com"},
                        }
                    }
                ],
            }
        )
        with patch("agent_lab.runtime.OfflineModel", return_value=fake):
            result = run("Open this link")
        self.assertEqual(result["tool_calls"], 0)
        self.assertEqual(result["status"], "completed")
        self.assertIn("tool_error", [event["kind"] for event in result["events"]])

    def test_schema_starter_and_reference(self):
        self.assertEqual(check_schema(TOOL_SCHEMA), [])
        for value in (
            None,
            [],
            {},
            {"type": "function", "function": {"parameters": []}},
            {"type": "function", "function": {"parameters": {"properties": []}}},
        ):
            with self.subTest(value=value):
                self.assertTrue(check_schema(value))
        broken = copy.deepcopy(TOOL_SCHEMA)
        broken["function"].update(name="shell", description="TODO")
        broken["function"]["parameters"].update(required=[], additionalProperties=True)
        broken["function"]["parameters"]["properties"]["query"] = {}
        self.assertGreaterEqual(len(check_schema(broken)), 5)

    def test_invalid_tool_request_becomes_an_observation(self):
        fake = MagicMock()
        fake.complete.side_effect = [
            {
                "role": "assistant",
                "tool_calls": [{"function": {"name": "shell", "arguments": {}}}],
            },
            {"role": "assistant", "content": "Tool rejected."},
        ]
        with patch("agent_lab.runtime.OfflineModel", return_value=fake):
            result = run("Find company capabilities")
        self.assertEqual(result["tool_calls"], 0)
        self.assertIn("tool_error", [e["kind"] for e in result["events"]])
        self.assertIn("not registered", result["messages"][-2]["content"])

    def test_provider_failure_never_silently_uses_offline(self):
        with patch.object(OllamaModel, "complete", side_effect=OSError("unavailable")):
            result = run("Find company capabilities", provider="ollama")
        self.assertEqual(result["status"], "provider_error")
        self.assertEqual(result["provider"], "ollama")
        self.assertEqual(result["tool_calls"], 0)

    def test_empty_or_excessive_provider_messages(self):
        fake = MagicMock()
        with patch("agent_lab.runtime.OfflineModel", return_value=fake):
            fake.complete.return_value = {"role": "assistant", "content": ""}
            self.assertEqual(run("Hello")["status"], "empty_response")
            fake.complete.return_value = {"tool_calls": [{}] * 9}
            self.assertEqual(run("Hello")["status"], "provider_error")
            fake.complete.return_value = {"tool_calls": [{"function": None}]}
            self.assertEqual(run("Hello", max_steps=1)["status"], "step_limit")
            self.assertEqual(run("Hello", mode="chatbot")["status"], "tool_not_exposed")

    def test_ollama_adapter_serializes_tool_context(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"message": {"role": "assistant", "content": "Done", "thinking": "private"}}
        ).encode()
        opener = MagicMock()
        opener.open.return_value = response
        with patch("urllib.request.build_opener", return_value=opener):
            message = OllamaModel().complete(
                [{"role": "user", "content": "Company capabilities"}], [TOOL_SCHEMA]
            )
            request = opener.open.call_args.args[0]
            self.assertEqual(json.loads(request.data)["tools"], [TOOL_SCHEMA])
            self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")
            self.assertEqual(message, {"role": "assistant", "content": "Done"})
            response.__enter__.return_value.read.return_value = (
                b'{"message": {"role":"system"}}'
            )
            with self.assertRaises(ValueError):
                OllamaModel().complete([], [])

    def test_cloudflare_adapter_uses_scoped_chat_completions_api(self):
        """Use the account-scoped OpenAI-compatible endpoint and normalize tool calls."""
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "search_documents",
                                        "arguments": '{"query":"AI"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        ).encode()
        messages = [{"role": "user", "content": "Find AI"}]
        with patch.dict(
            os.environ,
            {
                "CLOUDFLARE_ACCOUNT_ID": "a" * 32,
                "CLOUDFLARE_API_TOKEN": "secret-test-token",
                "CLOUDFLARE_MODEL": "@cf/zai-org/glm-4.7-flash",
            },
        ), patch("urllib.request.urlopen", return_value=response) as urlopen:
            message = CloudflareModel().complete(messages, TOOL_SCHEMAS)

        request = urlopen.call_args.args[0]
        context = urlopen.call_args.kwargs["context"]
        self.assertEqual(
            request.full_url,
            "https://api.cloudflare.com/client/v4/accounts/"
            + "a" * 32
            + "/ai/v1/chat/completions",
        )
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertEqual(
            request.get_header("Authorization"), "Bearer secret-test-token"
        )
        body = json.loads(request.data)
        self.assertEqual(body["model"], "@cf/zai-org/glm-4.7-flash")
        self.assertEqual(body["messages"], messages)
        self.assertEqual(body["tools"], TOOL_SCHEMAS)
        self.assertFalse(body["parallel_tool_calls"])
        self.assertEqual(message["tool_calls"][0]["id"], "call-1")
        self.assertEqual(
            message["tool_calls"][0]["function"]["arguments"], {"query": "AI"}
        )

    def test_cloudflare_adapter_sends_openai_tool_observation_shape(self):
        """Keep the provider-specific tool protocol out of the shared runtime."""
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "Evidence received."}}
                ]
            }
        ).encode()
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "cf-call-1",
                        "type": "function",
                        "function": {
                            "name": "search_documents",
                            "arguments": {"query": "AI"},
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_name": "search_documents",
                "tool_call_id": "cf-call-1",
                "content": '{"matches": []}',
            },
        ]
        with patch.dict(
            os.environ,
            {
                "CLOUDFLARE_ACCOUNT_ID": "a" * 32,
                "CLOUDFLARE_API_TOKEN": "secret-test-token",
            },
        ), patch("urllib.request.urlopen", return_value=response) as urlopen:
            CloudflareModel().complete(messages, [TOOL_SCHEMA])
        body = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(
            body["messages"][1],
            {"role": "tool", "tool_call_id": "cf-call-1", "content": '{"matches": []}'},
        )

    def test_cloudflare_adapter_rejects_missing_or_invalid_configuration(self):
        """Fail closed before making a remote request if configuration is incomplete."""
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "CLOUDFLARE_API_TOKEN"):
                CloudflareModel().complete([], [])
        with patch.dict(
            os.environ,
            {
                "CLOUDFLARE_ACCOUNT_ID": "not-an-account-id",
                "CLOUDFLARE_API_TOKEN": "secret-test-token",
            },
        ), patch("urllib.request.urlopen") as urlopen:
            with self.assertRaisesRegex(ValueError, "CLOUDFLARE_ACCOUNT_ID"):
                CloudflareModel().complete([], [])
            urlopen.assert_not_called()

    def test_cloudflare_provider_can_drive_the_shared_agent_loop(self):
        """The debugger's normal runtime accepts Cloudflare without changing tool dispatch."""
        fake = MagicMock()
        fake.name = "cloudflare-workers-ai"
        fake.complete.side_effect = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "provider-call-77",
                        "function": {
                            "name": "search_documents",
                            "arguments": {"query": "AI capabilities"},
                        },
                    }
                ],
            },
            {"role": "assistant", "content": "[DOC-001] Verified evidence."},
        ]
        with patch("agent_lab.runtime.CloudflareModel", return_value=fake):
            result = run("AI capabilities", provider="cloudflare")
        self.assertEqual(result["provider"], "cloudflare-workers-ai")
        self.assertEqual(result["tool_calls"], 1)
        self.assertIn("DOC-001", result["answer"])
        observation = next(
            event["payload"]["message"]
            for event in result["events"]
            if event["kind"] == "observation"
        )
        self.assertEqual(observation["tool_call_id"], "provider-call-77")

    def test_env_file_loader_keeps_existing_environment_and_ignores_comments(self):
        """Load simple local key-values without overriding shell-provided secrets."""
        with tempfile.TemporaryDirectory() as tmp:
            env_path = os.path.join(tmp, ".env")
            with open(env_path, "w", encoding="utf-8") as env_file:
                env_file.write(
                    '# local settings\nCLOUDFLARE_MODEL="@cf/qwen/qwen3.8-27b"\n'
                )
                env_file.write('CLOUDFLARE_API_TOKEN="from-file"\nEMPTY=\n')
            with patch.dict(
                os.environ, {"CLOUDFLARE_API_TOKEN": "from-shell"}, clear=True
            ):
                load_env_file(env_path)
                self.assertEqual(os.environ["CLOUDFLARE_API_TOKEN"], "from-shell")
                self.assertEqual(os.environ["CLOUDFLARE_MODEL"], "@cf/qwen/qwen3.8-27b")
                self.assertEqual(os.environ["EMPTY"], "")


if __name__ == "__main__":
    unittest.main()
