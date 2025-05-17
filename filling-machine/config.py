import json
import os

class Config:
    def __init__(self, path="config.json"):
        full = os.path.join(os.path.dirname(__file__), path)
        with open(full, encoding="utf-8") as f:
            content = f.read()
            if not content.strip():
                raise ValueError(f"Config file {full!r} is empty or missing JSON content")
            try:
                data = json.loads(content)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in config file {full!r}: {e}")
        self._data = data

    def get(self, key: str):
        return self._data[key]

    @property
    def volumes(self):
        """
        Returns only the numeric pour‐volume entries (e.g. 'Brie', 'Food_Service', etc.),
        excluding any '_mould' weights or other settings.
        """
        return {
            k: v
            for k, v in self._data.items()
            if not k.endswith("_mould")
               and isinstance(v, (int, float))
        }

    @property
    def mould_weights(self):
        """
        Returns only the numeric mould‐tare entries (keys ending in '_mould').
        """
        return {
            k: v
            for k, v in self._data.items()
            if k.endswith("_mould")
               and isinstance(v, (int, float))
        }