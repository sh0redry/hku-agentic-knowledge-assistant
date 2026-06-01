import config


def create_chat_model():
    """Create the chat model configured for the project.

    Gemini is the default provider for cloud development. Ollama remains
    available as an optional local provider for offline experiments.
    """
    provider = config.LLM_PROVIDER

    if provider == "gemini":
        if not config.GEMINI_API_KEY:
            raise RuntimeError(
                "GOOGLE_API_KEY is required when LLM_PROVIDER=gemini. "
                "Create project/.env from project/.env.example and add your Gemini API key."
            )

        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=config.LLM_MODEL,
            temperature=config.LLM_TEMPERATURE,
            google_api_key=config.GEMINI_API_KEY,
        )

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=config.LLM_MODEL,
            temperature=config.LLM_TEMPERATURE,
            base_url=config.OLLAMA_BASE_URL,
        )

    raise ValueError(
        f"Unsupported LLM_PROVIDER '{provider}'. Supported providers: gemini, ollama."
    )


def create_rewrite_model():
    """Create the cheaper model used for query rewriting and light classification."""
    provider = config.QUERY_REWRITE_PROVIDER

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=config.QUERY_REWRITE_MODEL,
            temperature=0,
            base_url=config.OLLAMA_BASE_URL,
        )

    return create_chat_model()
