"""Importing this package registers every extractor."""
# noqa: F401 - imported only to self-register
from pith.pipeline.extractors import (  # noqa: F401
    document, image, media, pdf, text, web,
)
