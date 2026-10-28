"""Provider connections and Chat Completions/Responses adapters; keys stay in .env."""
import os
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

PROVIDERS = {
    "openai": {"label": "OpenAI API", "base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY", "model": "gpt-4.1-mini"},
    "openrouter": {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY", "model": "google/gemini-2.5-flash"},
    "gemini": {"label": "Gemini API", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key_env": "GEMINI_API_KEY", "model": "gemini-2.5-flash"},
    "claude": {"label": "Claude API", "base_url": "https://api.anthropic.com/v1", "key_env": "ANTHROPIC_API_KEY", "model": "claude-sonnet-4-6"},
    "codex": {"label": "Codex (OpenAI API)", "base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY", "model": "gpt-5.1-codex"},
    "deepseek": {"label": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "key_env": "DEEPSEEK_API_KEY", "model": "deepseek-chat"},
    "custom": {"label": "Custom (OpenAI compatible)", "base_url": "", "key_env": "CUSTOM_API_KEY", "model": ""},
}

SELECTABLE_PROVIDERS = ("openrouter", "gemini", "claude", "codex", "openai")
PROVIDER_LINKS = {
    "openrouter": ("https://openrouter.ai/settings/keys", "https://openrouter.ai/docs/quickstart"),
    "gemini": ("https://aistudio.google.com/apikey", "https://ai.google.dev/gemini-api/docs/openai"),
    "claude": ("https://platform.claude.com/settings/keys", "https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk"),
    "codex": ("https://platform.openai.com/api-keys", "https://developers.openai.com/api/docs/models/gpt-5.1-codex"),
    "openai": ("https://platform.openai.com/api-keys", "https://developers.openai.com/api/docs/quickstart"),
}


def provider_for(processing):
    provider = processing.get("provider")
    if provider:
        if provider not in PROVIDERS:
            raise ValueError("Unknown API provider")
        return provider
    host = urlsplit(processing.get("base_url") or PROVIDERS["openrouter"]["base_url"]).hostname or ""
    if host == "generativelanguage.googleapis.com":
        return "gemini"
    if host == "api.anthropic.com":
        return "claude"
    if host == "api.openai.com":
        return "codex" if "codex" in str(processing.get("model") or "").lower() else "openai"
    if host == "api.deepseek.com":
        return "deepseek"
    return "openrouter" if host == "openrouter.ai" else "custom"


def normalize_base_url(value):
    parts = urlsplit(str(value).strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Base URL must be an HTTP(S) address without credentials, query or fragment")
    path = parts.path.rstrip("/")
    for suffix in ("/chat/completions", "/responses"):
        if path.endswith(suffix):
            path = path[:-len(suffix)]
    if not path:
        path = "/v1"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def connection_config(processing):
    provider = provider_for(processing)
    defaults = PROVIDERS[provider]
    return {"provider": provider, "base_url": normalize_base_url(processing.get("base_url") or defaults["base_url"]),
            "model": str(processing.get("model", defaults["model"])).strip()}


def get_api_key(provider):
    names = [PROVIDERS[provider]["key_env"]]
    if provider == "openrouter":
        names.append("OPENROUTER_API_KEY_BACKUP")
    for name in names:
        key = os.getenv(name, "").strip()
        if key:
            return key, name
    return "", names[0]


def require_api_key(provider):
    key, name = get_api_key(provider)
    if not key:
        raise ValueError(f"Missing API key: set {name} in .env")
    return key


def uses_responses(base_url, model):
    """Official Codex models only accept the Responses API."""
    return urlsplit(str(base_url)).hostname == "api.openai.com" and "codex" in model.lower()


def _as_dict(value):
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)
    return vars(value)


def completion_payload(base_url, model, messages, **options):
    """Translate our chat messages, images and tool history into the selected API."""
    if not uses_responses(base_url, model):
        if urlsplit(str(base_url)).hostname == "api.anthropic.com":
            # Newer Claude models reject temperature=0; JSON is requested in prompts.
            options.pop("temperature", None)
            options.pop("response_format", None)
        return "/chat/completions", {"model": model, "messages": messages, **options}

    inputs = []
    for message in messages:
        msg = _as_dict(message)
        if msg.get("_response_output"):
            inputs.extend(msg["_response_output"])
            continue
        if msg["role"] == "tool":
            inputs.append({"type": "function_call_output", "call_id": msg["tool_call_id"], "output": msg["content"]})
            continue
        content = msg.get("content")
        if isinstance(content, list):
            converted = []
            for part in content:
                if part["type"] == "text":
                    converted.append({"type": "input_text", "text": part["text"]})
                elif part["type"] == "image_url":
                    image = part["image_url"]
                    converted.append({"type": "input_image", "image_url": image["url"], "detail": image.get("detail", "auto")})
            content = converted
        if content:
            inputs.append({"role": msg["role"], "content": content})
        for call in msg.get("tool_calls") or []:
            call = _as_dict(call)
            function = _as_dict(call["function"])
            inputs.append({"type": "function_call", "call_id": call["id"], "name": function["name"], "arguments": function["arguments"]})

    payload = {"model": model, "input": inputs, "store": False, "reasoning": {"effort": "low"},
               "include": ["reasoning.encrypted_content"]}
    # Codex does not accept temperature. Prompts already ask for JSON where needed.
    token_limit = options.get("max_completion_tokens", options.get("max_tokens"))
    if token_limit is not None:
        payload["max_output_tokens"] = max(4096, token_limit)
    if options.get("tools"):
        payload["tools"] = [{"type": "function", "strict": False, **tool["function"]} for tool in options["tools"]]
        payload["tool_choice"] = options.get("tool_choice", "auto")
    return "/responses", payload


def completion_text(payload, responses=False):
    if not isinstance(payload, dict):
        raise ValueError("Provider did not return a valid response")
    if responses:
        if payload.get("status") not in (None, "completed"):
            raise ValueError("Provider did not finish the response")
        text = "".join(part.get("text", "") for item in payload.get("output", [])
                       if item.get("type") == "message" for part in item.get("content", [])
                       if part.get("type") == "output_text")
    else:
        choices = payload.get("choices") or []
        text = (choices[0].get("message") or {}).get("content") if choices else None
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Provider did not return a text response")
    return text


def completion_request(connection, key, messages, **options):
    path, payload = completion_payload(connection["base_url"], connection["model"], messages, **options)
    return connection["base_url"] + path, {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, payload


def create_completion(client, *, model, messages, **options):
    """Keep all pipeline stages on one protocol adapter, including tool loops."""
    timeout = options.pop("timeout", None)
    path, payload = completion_payload(getattr(client, "base_url", ""), model, messages, **options)
    if timeout is not None:
        payload["timeout"] = timeout
    if path != "/responses":
        return client.chat.completions.create(**payload)
    response = client.responses.create(**payload)
    raw = response.model_dump(exclude_none=True)
    if raw.get("status") != "completed":
        raise ValueError("Provider did not finish the response")
    calls = [SimpleNamespace(id=item["call_id"], type="function", function=SimpleNamespace(name=item["name"], arguments=item["arguments"]))
             for item in raw.get("output", []) if item.get("type") == "function_call"]
    content = completion_text(raw, responses=True) if not calls else None
    message = SimpleNamespace(role="assistant", content=content, tool_calls=calls,
                              _response_output=raw.get("output", []))
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="tool_calls" if calls else "stop")])
