from collections import OrderedDict
from hashlib import sha256
from typing import Any


class LRUCache:
    def __init__(self, max_size: int = 256):
        self.max_size = max_size
        self._items: OrderedDict[str, Any] = OrderedDict()

    def get(self, key: str):
        if key not in self._items:
            return None
        value = self._items.pop(key)
        self._items[key] = value
        return value

    def set(self, key: str, value: Any) -> None:
        if key in self._items:
            self._items.pop(key)
        self._items[key] = value
        while len(self._items) > self.max_size:
            self._items.popitem(last=False)


def cache_key(*parts: str) -> str:
    joined = "\n\n---\n\n".join(parts)
    return sha256(joined.encode("utf-8")).hexdigest()


rewrite_cache = LRUCache(max_size=512)
answer_cache = LRUCache(max_size=256)
