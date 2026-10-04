"""Explicit extension boundary for optional caption providers.

No network provider is enabled by default. Adapters receive a snapshot during
batch exports, must be thread-safe, and must return the existing Caption model.
"""
from typing import Protocol

from .caption import Caption, CaptionOptions, build_caption
from .config import Config
from .models import Title


class CaptionProvider(Protocol):
    name: str

    def generate(self, title: Title, config: Config, options: CaptionOptions) -> Caption:
        ...


class TemplateCaptionProvider:
    name = "local-templates"

    def generate(self, title: Title, config: Config, options: CaptionOptions) -> Caption:
        return build_caption(title, config, options)
