"""Numeric backend spec values are validated when the registry is built."""
import tomllib

import pytest

from pith.config import Config, ConfigError
from pith.providers.registry import Registry


@pytest.mark.parametrize("key,bad", [("timeout", '"30"'), ("timeout", "0"), ("timeout", "true"),
                                     ("context_window", '"8192"'), ("context_window", "-1")])
def test_spec_numbers_must_be_positive_numbers(key, bad):
    """A string timeout/context_window would crash later, past distill's fallback."""
    spec = tomllib.loads('a = { type = "openai_compat", base_url = "http://localhost:1/v1", '
                         f'model = "m", {key} = {bad} }}')["a"]
    cfg = Config(home=None, db_path=None, blobs_dir=None, vault_dir=None, backends={"a": spec})
    with pytest.raises(ConfigError, match=key):
        Registry.from_config(cfg)
