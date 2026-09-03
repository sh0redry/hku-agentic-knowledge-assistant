import config


class ChatModelWithFallback:
    """Wrap a primary chat model with a provider-level fallback."""

    def __init__(self, primary, fallback=None, config_args=None, config_kwargs=None):
        self.primary = primary
        self.fallback = fallback
        self.config_args = config_args or ()
        self.config_kwargs = config_kwargs or {}

    def _apply_config(self, runnable):
        if not self.config_args and not self.config_kwargs:
            return runnable
        return runnable.with_config(*self.config_args, **self.config_kwargs)

    def _with_fallback(self, primary_runnable, fallback_runnable=None):
        primary_runnable = self._apply_config(primary_runnable)
        if not fallback_runnable:
            return primary_runnable
        return primary_runnable.with_fallbacks([self._apply_config(fallback_runnable)])

    def invoke(self, *args, **kwargs):
        return self._with_fallback(self.primary, self.fallback).invoke(*args, **kwargs)

    def bind_tools(self, tools, **kwargs):
        primary = self.primary.bind_tools(tools, **kwargs)
        fallback = self.fallback.bind_tools(tools, **kwargs) if self.fallback else None
        return self._with_fallback(primary, fallback)

    def with_structured_output(self, schema, **kwargs):
        primary = self.primary.with_structured_output(schema, **kwargs)
        fallback = (
            self.fallback.with_structured_output(schema, **kwargs)
            if self.fallback
            else None
        )
        return self._with_fallback(primary, fallback)

    def with_config(self, *args, **kwargs):
        return ChatModelWithFallback(self.primary, self.fallback, args, kwargs)


def _create_provider_model(provider, model):
    if provider == "deepseek":
        if not config.DEEPSEEK_API_KEY:
            raise RuntimeError(
                "DEEPSEEK_API_KEY is required when LLM_PROVIDER=deepseek. "
                "Create project/.env from project/.env.example and add your DeepSeek API key."
            )

        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            temperature=config.LLM_TEMPERATURE,
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
        )

    if provider == "gemini":
        if not config.GEMINI_API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY or GOOGLE_API_KEY is required when LLM_PROVIDER=gemini. "
                "Create project/.env from project/.env.example and add your Gemini API key."
            )

        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model,
            temperature=config.LLM_TEMPERATURE,
            google_api_key=config.GEMINI_API_KEY,
        )

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=model,
            temperature=config.LLM_TEMPERATURE,
            base_url=config.OLLAMA_BASE_URL,
        )

    raise ValueError(
        f"Unsupported LLM provider '{provider}'. Supported providers: deepseek, gemini, ollama."
    )


def _provider_has_credentials(provider):
    if provider == "deepseek":
        return bool(config.DEEPSEEK_API_KEY)
    if provider == "gemini":
        return bool(config.GEMINI_API_KEY)
    return True


def create_chat_model():
    """Create the chat model configured for the project.

    DeepSeek is the default provider. Gemini is configured as the default
    fallback provider when its API key is available.
    """
    primary = _create_provider_model(config.LLM_PROVIDER, config.LLM_MODEL)
    fallback = None
    fallback_provider = config.LLM_FALLBACK_PROVIDER

    if (
        config.LLM_FALLBACK_ENABLED
        and fallback_provider
        and fallback_provider != "none"
        and fallback_provider != config.LLM_PROVIDER
    ):
        if _provider_has_credentials(fallback_provider):
            fallback = _create_provider_model(fallback_provider, config.LLM_FALLBACK_MODEL)
        else:
            print(
                f"LLM fallback provider '{fallback_provider}' is configured but missing credentials; "
                "continuing with the primary model only."
            )

    return ChatModelWithFallback(primary, fallback)


def create_rewrite_model():
    """Create the cheaper model used for query rewriting and light classification."""
    return ChatModelWithFallback(
        _create_provider_model(config.QUERY_REWRITE_PROVIDER, config.QUERY_REWRITE_MODEL),
        _create_provider_model(config.LLM_FALLBACK_PROVIDER, config.LLM_FALLBACK_MODEL)
        if (
            config.LLM_FALLBACK_ENABLED
            and config.LLM_FALLBACK_PROVIDER != config.QUERY_REWRITE_PROVIDER
            and config.LLM_FALLBACK_PROVIDER != "none"
            and _provider_has_credentials(config.LLM_FALLBACK_PROVIDER)
        )
        else None,
    )
