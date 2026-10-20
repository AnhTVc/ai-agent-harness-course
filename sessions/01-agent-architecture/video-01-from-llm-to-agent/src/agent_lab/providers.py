"""A deterministic teaching stand-in and an optional real local model adapter.

Both return the same assistant-message shape. The offline stand-in proves
runtime wiring only; it cannot measure LLM reasoning or answer quality.
"""

import json
import os
import re
from urllib.request import Request
from .network import verified_https_context


def evidence_answer(output):
    """Render only facts present in the observation for the offline stand-in."""
    if output.get("error"):
        return "The tool could not execute: " + output["error"]
    if output.get("tool") == "calculate":
        return f"Calculation result: {output['expression']} = {output['result']}."
    if output.get("tool") == "search_weather":
        # The response cites the matched place, observation time, and source.
        place = output.get("matched_location", {})
        location = ", ".join(
            dict.fromkeys(
                place.get(key, "")
                for key in ("name", "admin1", "country")
                if place.get(key)
            )
        )
        current = output.get("current", {})
        return (
            f"Current weather for {location or 'the matched location'} at {output.get('observed_at')}: "
            f"{output.get('condition')}, {current.get('temperature')} {current.get('temperature_unit')}; "
            f"feels like {current.get('feels_like')} {current.get('temperature_unit')}; "
            f"humidity {current.get('relative_humidity')}{current.get('humidity_unit')}. "
            f"Source: {output.get('source')}."
        )
    matches = output.get("matches", [])
    return (
        " ".join(f"[{p['id']}] {p['text']}" for p in matches)
        or "No matching document was found in the classroom fixture."
    )


def _verified_cloudflare_context():
    """Keep the provider helper name while sharing one trusted CA policy."""
    return verified_https_context()


def _cloudflare_messages(messages):
    """Serialize debugger messages using the OpenAI tool-call wire protocol."""
    wire_messages = []
    for message in messages:
        # The shared runtime keeps tool names for Ollama; Cloudflare requires
        # the matching provider call ID and does not accept this internal field.
        if message.get("role") == "tool":
            call_id = message.get("tool_call_id")
            if not isinstance(call_id, str) or not call_id:
                raise ValueError("Cloudflare tool observations require a tool_call_id.")
            wire_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": message.get("content", ""),
                }
            )
            continue
        # Runtime-facing arguments are objects, while the OpenAI-compatible
        # conversation protocol requires function arguments as a JSON string.
        if message.get("role") == "assistant" and message.get("tool_calls"):
            assistant = {"role": "assistant", "content": message.get("content") or ""}
            calls = []
            for call in message["tool_calls"]:
                function = call.get("function", {})
                arguments = function.get("arguments", {})
                if isinstance(arguments, dict):
                    arguments = json.dumps(
                        arguments, ensure_ascii=False, separators=(",", ":")
                    )
                calls.append(
                    {
                        "id": call.get("id"),
                        "type": "function",
                        "function": {
                            "name": function.get("name"),
                            "arguments": arguments,
                        },
                    }
                )
            assistant["tool_calls"] = calls
            wire_messages.append(assistant)
            continue
        wire_messages.append(message)
    return wire_messages


class OfflineModel:
    """Rule-based tool selection for reliable recording and offline teaching."""

    name = "offline-rule-based"

    def complete(self, messages, tools):
        """Observe results first; otherwise route a classroom example by intent."""
        observations = [m for m in messages if m["role"] == "tool"]
        if observations:
            return {
                "role": "assistant",
                "content": evidence_answer(json.loads(observations[-1]["content"])),
            }
        prompt = next(m["content"] for m in messages if m["role"] == "user")
        available = {tool["function"]["name"] for tool in tools}
        # A visible answer-only branch makes the loop's two exits inspectable.
        if prompt.lower().strip(" .!?") in ("hello", "hi", "thanks"):
            return {
                "role": "assistant",
                "content": "Hello. Ask about the company documents to inspect a tool lookup.",
            }
        # Route weather questions to the read-only API tool, extracting a place
        # name so the geocoder receives a location rather than the full prompt.
        if "search_weather" in available and re.search(
            r"\b(weather|temperature)\b", prompt, re.I
        ):
            place = re.search(r"\b(?:in|for|at)\s+(.+?)\s*[?.!]*$", prompt, re.I)
            location = place.group(1).strip() if place else ""
            if location:
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "search_weather",
                                "arguments": {"location": location},
                            }
                        }
                    ],
                }
        # Route explicit arithmetic prompts only; natural-language questions
        # without a numeric expression remain ordinary document requests.
        if "calculate" in available and re.search(r"\d.*(?:\+|-|\*|/|%)", prompt):
            expression = re.sub(
                r"^\s*(?:please\s+)?(?:calculate|compute|solve|what(?:'s| is))\s*:?[\s]*",
                "",
                prompt,
                flags=re.I,
            )
            expression = expression.strip().rstrip("?.! ")
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "calculate",
                            "arguments": {"expression": expression},
                        }
                    }
                ],
            }
        if tools:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "search_documents",
                            "arguments": {"query": prompt},
                        }
                    }
                ],
            }
        return {
            "role": "assistant",
            "content": "I cannot verify company capabilities without a document tool and its result.",
        }


class OllamaModel:
    """Real tool calling through a fixed loopback Ollama endpoint.

    Only the server process reads the model name. The browser cannot override
    the endpoint, supply credentials, or direct requests to arbitrary hosts.
    """

    name = "ollama"

    def complete(self, messages, tools):
        """Send messages plus schemas; normalize the returned assistant message."""
        body = {
            "model": os.environ.get("OLLAMA_MODEL", "qwen3:8b"),
            "messages": messages,
            "tools": tools,
            "stream": False,
            "options": {"temperature": 0, "num_predict": 1024},
        }
        request = Request(
            "http://127.0.0.1:11434/api/chat",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # Ignore any HTTP proxy configuration: this provider is strictly local.
        from urllib.request import ProxyHandler, build_opener

        with build_opener(ProxyHandler({})).open(request, timeout=60) as response:
            message = json.loads(response.read(1_000_000))["message"]
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise ValueError("Unexpected provider message.")
        # Hidden reasoning is neither needed nor displayed as execution evidence.
        return {
            key: message[key]
            for key in ("role", "content", "tool_calls")
            if key in message
        }


class CloudflareModel:
    """Call a configured Workers AI model through its OpenAI-compatible API."""

    name = "cloudflare-workers-ai"

    def complete(self, messages, tools):
        """Send only lesson context and schemas; never include credentials in traces."""
        account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
        token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
        model = os.environ.get("CLOUDFLARE_MODEL", "@cf/zai-org/glm-4.7-flash").strip()
        if not token:
            raise ValueError(
                "CLOUDFLARE_API_TOKEN is required for Cloudflare Workers AI."
            )
        if not re.fullmatch(r"[a-fA-F0-9]{32}", account_id):
            raise ValueError(
                "CLOUDFLARE_ACCOUNT_ID must be a 32-character account identifier."
            )
        if not model or len(model) > 200:
            raise ValueError("CLOUDFLARE_MODEL must be a non-empty model identifier.")

        # The fixed account-scoped URL prevents user input from choosing a host.
        url = (
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
            "/ai/v1/chat/completions"
        )
        body = {
            "model": model,
            "messages": _cloudflare_messages(messages),
            "tools": tools,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "stream": False,
            "temperature": 0,
        }
        request = Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        from urllib.request import urlopen

        # Keep the token in the Authorization header and avoid retaining response data.
        with urlopen(
            request, timeout=60, context=_verified_cloudflare_context()
        ) as response:
            payload = json.loads(response.read(1_000_000))
        choices = payload.get("choices") if isinstance(payload, dict) else None
        if (
            not isinstance(choices, list)
            or not choices
            or not isinstance(choices[0], dict)
        ):
            raise ValueError("Cloudflare returned an unexpected chat completion.")
        message = choices[0].get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise ValueError("Cloudflare returned an unexpected assistant message.")

        # Normalize OpenAI-compatible JSON-string arguments for the runtime's
        # allowlisted executor, while preserving the model's proposed tool name.
        normalized_calls = []
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
                raise ValueError("Cloudflare returned an invalid tool call.")
            function = dict(call["function"])
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            if not isinstance(arguments, dict):
                raise ValueError("Cloudflare returned invalid tool arguments.")
            function["arguments"] = arguments
            call_id = call.get("id")
            if not isinstance(call_id, str) or not call_id or len(call_id) > 128:
                call_id = f"cloudflare-{len(messages)}-{len(normalized_calls) + 1}"
            normalized_calls.append(
                {"id": call_id, "type": "function", "function": function}
            )
        content = message.get("content") or ""
        if not isinstance(content, str):
            raise ValueError("Cloudflare assistant content must be text.")
        normalized = {"role": "assistant", "content": content}
        if normalized_calls:
            normalized["tool_calls"] = normalized_calls
        return normalized
