import json
import os

class Config:
    def __init__(self, path="config.json"):
        full = os.path.join(os.path.dirname(__file__), path)
        # remember file path for saving
        self._path = full
        with open(full, encoding="utf-8") as f:
            content = f.read()
            if not content.strip():
                raise ValueError(f"Config file {full!r} is empty or missing JSON content")
            try:
                data = json.loads(content)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in config file {full!r}: {e}")
        self._data = data

    def get(self, key: str, default=None):
        return self._data.get(key,
               self._data.get("flavours", {}).get(key,
               self._data.get("mould_weights", {}).get(key,
               default)))

    @property
    def volumes(self):
        """
        Returns the dict of flavour volumes.
        """
        return dict(self._data.get("flavours", {}))

    @property
    def mould_weights(self):
        """
        Returns the dict of mould tare weights.
        """
        return dict(self._data.get("mould_weights", {}))

    def set(self, key: str, value):
        """Set a config key to a new value in memory."""
        self._data[key] = value

    def save(self):
        """Persist current configuration back to the JSON file."""
        with open(self._path, 'w', encoding='utf-8') as f:
            json.dump(self._data, f, indent=2)