"""
YAML template loader for server structure definitions.
"""
import os
import yaml
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger("bot.templates")

DEFAULTS_DIR = os.path.join(os.path.dirname(__file__), "defaults")


class TemplateLoader:
    """Load, validate, and manage YAML server templates."""

    def __init__(self):
        self._templates: Dict[str, dict] = {}
        self._load_defaults()

    def _load_defaults(self):
        """Load all default templates from the defaults directory."""
        if not os.path.exists(DEFAULTS_DIR):
            logger.warning(f"Defaults directory not found: {DEFAULTS_DIR}")
            return

        for filename in os.listdir(DEFAULTS_DIR):
            if filename.endswith((".yaml", ".yml")):
                template_name = filename[:-5]  # Remove .yaml/.yml
                filepath = os.path.join(DEFAULTS_DIR, filename)
                try:
                    template = self._load_file(filepath)
                    self._templates[template_name] = template
                    logger.info(f"Loaded template: {template_name}")
                except Exception as e:
                    logger.error(f"Failed to load template {filename}: {e}")

    def _load_file(self, filepath: str) -> dict:
        """Load and parse a YAML file."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return self._validate_template(data)

    def _validate_template(self, data: dict) -> dict:
        """Validate template structure and apply defaults."""
        if not isinstance(data, dict):
            raise ValueError("Template must be a YAML mapping")

        # Ensure required fields
        template = {
            "name": data.get("name", "Unnamed Template"),
            "description": data.get("description", ""),
            "categories": data.get("categories", []),
            "roles": data.get("roles", []),
            "reaction_roles": data.get("reaction_roles", []),
            "welcome": data.get("welcome", {}),
        }

        # Validate categories
        for i, category in enumerate(template["categories"]):
            if not isinstance(category, dict):
                raise ValueError(f"Category {i} must be a mapping")
            if "name" not in category:
                raise ValueError(f"Category {i} missing 'name' field")
            template["categories"][i]["channels"] = category.get("channels", [])
            template["categories"][i]["permissions"] = category.get("permissions", {})

            # Validate channels
            for j, channel in enumerate(template["categories"][i]["channels"]):
                if not isinstance(channel, dict):
                    raise ValueError(f"Channel {j} in category '{category['name']}' must be a mapping")
                if "name" not in channel:
                    raise ValueError(f"Channel {j} in category '{category['name']}' missing 'name'")
                channel.setdefault("type", "text")
                channel.setdefault("nsfw", False)
                channel.setdefault("permissions", {})
                if channel["type"] not in ("text", "voice", "announcement", "category", "stage", "forum"):
                    raise ValueError(
                        f"Invalid channel type '{channel['type']}'. "
                        f"Valid: text, voice, announcement, category, stage, forum"
                    )

        # Validate roles
        for i, role in enumerate(template["roles"]):
            if not isinstance(role, dict):
                raise ValueError(f"Role {i} must be a mapping")
            if "name" not in role:
                raise ValueError(f"Role {i} missing 'name' field")
            role.setdefault("color", None)
            role.setdefault("hoist", False)
            role.setdefault("mentionable", False)
            role.setdefault("permissions", {})

        return template

    def list_templates(self) -> List[str]:
        """Return list of available template names."""
        return list(self._templates.keys())

    def get_template(self, name: str) -> Optional[dict]:
        """Get a template by name. Default templates are hot-reloaded from disk."""
        # For default templates, always reload from disk (hot-reload)
        default_path = os.path.join(DEFAULTS_DIR, f"{name}.yaml")
        if os.path.exists(default_path):
            try:
                return self._load_file(default_path)
            except Exception as e:
                logger.error(f"Failed to reload template {name}: {e}")
                return self._templates.get(name)
        return self._templates.get(name)

    def add_template(self, name: str, template: dict):
        """Add or overwrite a template."""
        validated = self._validate_template(template)
        self._templates[name] = validated
        logger.info(f"Added custom template: {name}")

    def remove_template(self, name: str) -> bool:
        """Remove a custom template (cannot remove defaults)."""
        if name in self._templates:
            default_path = os.path.join(DEFAULTS_DIR, f"{name}.yaml")
            if os.path.exists(default_path):
                return False  # Cannot remove defaults
            del self._templates[name]
            logger.info(f"Removed template: {name}")
            return True
        return False

    def template_exists(self, name: str) -> bool:
        """Check if a template exists."""
        return name in self._templates