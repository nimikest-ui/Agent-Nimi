"""
LLM Provider - Base class and registry
"""
from abc import ABC, abstractmethod
from typing import Generator


class LLMProvider(ABC):
    """Base class for all LLM providers."""

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def chat(self, messages: list[dict], stream: bool = True) -> str | Generator[str, None, None]:
        """Send messages to the LLM and get a response.
        
        Args:
            messages: List of {"role": "system"|"user"|"assistant", "content": "..."}
            stream: If True, yield chunks. If False, return full string.
        """
        ...

    @abstractmethod
    def name(self) -> str:
        """Provider display name."""
        ...

    @abstractmethod
    def test_connection(self) -> bool:
        """Test if the provider is available."""
        ...

    def deep_test_connection(self) -> tuple[bool, str]:
        """Test connection with a real inference request.
        
        Returns (ok, error_message).  Subclasses may override for
        provider-specific diagnostics.  The default falls back to
        test_connection() and returns a generic message.
        """
        try:
            ok = self.test_connection()
            return (True, "") if ok else (False, "connection test failed")
        except Exception as e:
            return False, str(e)


_PROVIDERS: dict[str, type[LLMProvider]] = {}


def register_provider(name: str):
    """Decorator to register a provider class."""
    def wrapper(cls):
        _PROVIDERS[name] = cls
        return cls
    return wrapper


def get_provider(name: str, config: dict) -> LLMProvider:
    """Get a configured provider instance."""
    if name not in _PROVIDERS:
        raise ValueError(f"Unknown provider: {name}. Available: {list(_PROVIDERS.keys())}")
    return _PROVIDERS[name](config)


def list_providers() -> list[str]:
    """List available provider names."""
    return list(_PROVIDERS.keys())
