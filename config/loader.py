# Version: 3.2.2
"""
Article Finder v3 - Configuration Loader
"""

import os
from pathlib import Path
from typing import Any, Optional
import yaml


CONFIG_DIR = Path(__file__).parent
DEFAULT_CONFIG = CONFIG_DIR / "settings.yaml"
LOCAL_CONFIG = CONFIG_DIR / "settings.local.yaml"


_config_cache: Optional[dict] = None


def load_config(reload: bool = False) -> dict:
    """
    Load configuration from YAML files.
    
    Priority:
    1. settings.local.yaml (user overrides, not in git)
    2. settings.yaml (defaults)
    3. Environment variables (AF_* prefix)
    """
    global _config_cache
    
    if _config_cache is not None and not reload:
        return _config_cache
    
    config = {}
    
    # Load default config
    if DEFAULT_CONFIG.exists():
        with open(DEFAULT_CONFIG) as f:
            config = yaml.safe_load(f) or {}
    
    # Override with local config
    if LOCAL_CONFIG.exists():
        with open(LOCAL_CONFIG) as f:
            local = yaml.safe_load(f) or {}
            config = _deep_merge(config, local)
    
    # Override with environment variables
    config = _apply_env_overrides(config)
    
    # Resolve paths relative to project root
    project_root = CONFIG_DIR.parent
    if 'paths' in config:
        for key, value in config['paths'].items():
            if isinstance(value, str) and not Path(value).is_absolute():
                config['paths'][key] = str(project_root / value)
    
    _config_cache = config
    return config


def get(key: str, default: Any = None) -> Any:
    """
    Get a config value by dot-notation key.
    
    Example:
        get('apis.openalex.email')
        get('triage.send_to_eater_threshold', 0.7)
    """
    config = load_config()
    
    keys = key.split('.')
    value = config
    
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            return default
    
    return value


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dictionaries."""
    result = base.copy()
    
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    
    return result


def _apply_env_overrides(config: dict) -> dict:
    """Apply environment variable overrides."""
    # AF_APIS_OPENALEX_EMAIL -> apis.openalex.email
    prefix = "AF_"
    
    for key, value in os.environ.items():
        if key.startswith(prefix):
            path = key[len(prefix):].lower().split('_')
            _set_nested(config, path, value)
    
    return config


def _set_nested(d: dict, keys: list, value: str) -> None:
    """Set a nested dictionary value."""
    for key in keys[:-1]:
        if key not in d:
            d[key] = {}
        d = d[key]
    
    # Try to parse value as appropriate type
    if value.lower() in ('true', 'false'):
        value = value.lower() == 'true'
    else:
        try:
            value = int(value)
        except ValueError:
            try:
                value = float(value)
            except ValueError:
                pass
    
    d[keys[-1]] = value


def ensure_directories() -> None:
    """Create all configured directories."""
    config = load_config()
    
    for key, path in config.get('paths', {}).items():
        p = Path(path)
        if p.exists():
            if p.is_dir() or p.is_file():
                continue
        # Treat file-like paths (e.g., database) as parent dirs
        if p.suffix:
            p.parent.mkdir(parents=True, exist_ok=True)
        else:
            p.mkdir(parents=True, exist_ok=True)
