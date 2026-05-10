"""
LLM Provider Factory - Dynamically instantiates LangChain chat models.
Supports: Ollama (local), OpenAI, Anthropic, Groq, Gemini, and a Mock provider for testing.
"""
from langchain_core.language_models.chat_models import BaseChatModel


class LLMProviderFactory:
    """Factory class to create LLM instances based on provider name."""

    SUPPORTED_PROVIDERS = ["ollama", "openai", "anthropic", "groq", "gemini", "mock"]

    @staticmethod
    def create_model(provider: str, model_name: str, callbacks=None, **kwargs) -> BaseChatModel:
        """
        Create and return a LangChain chat model instance.

        Args:
            provider: The LLM provider name (e.g., 'ollama', 'openai').
            model_name: The specific model to use (e.g., 'llama3', 'gpt-4o').
            **kwargs: Additional keyword arguments passed to the model constructor.

        Returns:
            A BaseChatModel instance.

        Raises:
            ValueError: If the provider is not supported.
            ImportError: If the required package for a provider is not installed.
        """
        provider = provider.lower()

        if provider == "ollama":
            try:
                from langchain_community.chat_models import ChatOllama
                return ChatOllama(model=model_name, callbacks=callbacks or [], **kwargs)
            except ImportError:
                raise ImportError(
                    "Please install langchain-community to use the Ollama provider: "
                    "pip install langchain-community"
                )

        elif provider == "openai":
            try:
                from langchain_openai import ChatOpenAI
                return ChatOpenAI(model=model_name, callbacks=callbacks or [], **kwargs)
            except ImportError:
                raise ImportError(
                    "Please install langchain-openai to use the OpenAI provider: "
                    "pip install langchain-openai"
                )

        elif provider == "anthropic":
            try:
                from langchain_anthropic import ChatAnthropic
                return ChatAnthropic(model_name=model_name, callbacks=callbacks or [], **kwargs)
            except ImportError:
                raise ImportError(
                    "Please install langchain-anthropic to use the Anthropic provider: "
                    "pip install langchain-anthropic"
                )

        elif provider == "groq":
            try:
                from langchain_groq import ChatGroq
                return ChatGroq(model_name=model_name, callbacks=callbacks or [], **kwargs)
            except ImportError:
                raise ImportError(
                    "Please install langchain-groq to use the Groq provider: "
                    "pip install langchain-groq"
                )

        elif provider == "gemini":
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
                return ChatGoogleGenerativeAI(model=model_name, callbacks=callbacks or [], **kwargs)
            except ImportError:
                raise ImportError(
                    "Please install langchain-google-genai to use the Gemini provider: "
                    "pip install langchain-google-genai"
                )

        elif provider == "mock":
            from langchain_community.chat_models import FakeListChatModel
            responses = kwargs.pop("responses", ["Mock response"])
            return FakeListChatModel(responses=responses, **kwargs)

        else:
            raise ValueError(
                f"Unsupported provider: '{provider}'. "
                f"Supported providers: {LLMProviderFactory.SUPPORTED_PROVIDERS}"
            )
