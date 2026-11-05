"""Importing this package registers every extractor."""
from infoparser.pipeline.extractors import document, image, media, pdf, text, web  # noqa: F401  (self-register)
