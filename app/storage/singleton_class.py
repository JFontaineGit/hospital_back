from pydantic import BaseModel
from typing import Optional, Any, Dict

from uuid import UUID, uuid4

from cachetools import cached, TTLCache
from functools import wraps

from datetime import datetime, timedelta

from time import time, sleep

from pathlib import Path

from rich.console import Console

import orjson

import mmap

import threading

import os

console = Console()

STORAGE_PATH: Path = (Path(__file__).parent / "storage.json").resolve()

def timeit(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time()
        result = func(*args, **kwargs)
        end = time()
        print(f"Function {func.__name__!r} executed in {(end-start):.4f}s")
        return result
    return wrapper

class PurgeMeta(type):
    ignore_methods = {"__init__", "__new__", "create_table", "purge_expired"}

    def __new__(mcs, name, bases, namespace):
        for attr, val in namespace.items():
            if callable(val) and not attr.startswith('_') and attr not in mcs.ignore_methods:
                namespace[attr] = mcs.wrap_with_purge(val)
        return super().__new__(mcs, name, bases, namespace)

    @staticmethod
    def wrap_with_purge(method):
        from functools import wraps
        @wraps(method)
        @timeit  # mantiene tu medición de tiempos
        def wrapper(self, *args, **kwargs):
            table_name = kwargs.get("table_name")
            if table_name:
                # Purga centralizada
                self.purge_expired(table_name)
            return method(self, *args, **kwargs)
        return wrapper

def fecha_encoder(o):
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, UUID):
        return str(o)
    return o

class Response(BaseModel):
    key: str
    value: Any
    expired: Optional[datetime] = None
    created: Optional[datetime] = None
    updated: Optional[datetime] = None
    id: Optional[UUID] = None

class Item(Response):
    pass

class GetItem(BaseModel):
    key: str
    value: Optional[Response] = None

class SetItem(Response):
    key: Optional[str] = None

class Table(BaseModel):
    name: str
    items: Optional[Dict[str, Item | SetItem]]

class Storage(BaseModel):
    tables: Dict[str, Table]


class Singleton(metaclass=PurgeMeta):
    _instance = None
    _cache = TTLCache(maxsize=100, ttl=timedelta(minutes=15).total_seconds())
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.__init_storage()
        else:
            pass

        return cls._instance

    def purge_expired(self, table_name: str) -> None:
        """
        Elimina en bloque las claves expiradas de self.data.tables[table_name].items.
        """
        items = self.data.tables[table_name].items
        now = datetime.now()
        # Filtramos sólo los no-expirados
        self.data.tables[table_name].items = {
            k: v for k, v in items.items()
            if v.expired > now
        }

    def __init_storage(self):
        self._lock = threading.Lock()
        self._flush_event = threading.Event()
        self.data = None
        self._dirty = False
        if not STORAGE_PATH.exists():
            STORAGE_PATH.touch()
            STORAGE_PATH.write_bytes(orjson.dumps({"tables": {}}, default=str))
        self._load()

        t = threading.Thread(target=self._auto_flush, daemon=True)
        t.start()


    def _load(self):
        raw = STORAGE_PATH.read_bytes()
        self.data = Storage.model_validate_json(raw)


    def _auto_flush(self):
        while True:
            # Bloquea hasta que haya trabajo o tras 1 segundo despierta de todas formas
            self._flush_event.wait(timeout=1)
            with self._lock:
                if self._dirty:
                    # Serializa TODO el estado actual
                    data_bytes = orjson.dumps(self.data.model_dump(), default=fecha_encoder)
                    STORAGE_PATH.write_bytes(data_bytes)
                    self._dirty = False
                # Resetea el evento
                self._flush_event.clear()

    def _mark_dirty(self):
        with self._lock:
            self._dirty = True
            self._flush_event.set()

    def create_table(self, table_name: str):
        self._load()
        if table_name in self.data.tables:
            return None
        table = Table(
            name=table_name,
            items={}
        )
        self.data.tables[table_name] = table
        print(self.data)
        self._mark_dirty()
        return table

    @cached(_cache)
    def get_all(self, table_name: str = None) -> Dict[Any, Any]:
        self._load()
        return self.data.tables.get(table_name, {}).items

    @cached(_cache)
    def get(self, key: str, table_name: str) -> GetItem | None:
        self._load()
        return self.data.tables[table_name].items.get(key, None)


    def set(self, key = None, value = None, table_name: str = "") -> SetItem:
        item = SetItem(
            key=key,
            value=value,
            created=datetime.now(),
            updated=datetime.now(),
            id=uuid4(),
            expired=datetime.now() + timedelta(minutes=15)
        )
        self.data.tables[table_name].items[key] = item
        self._mark_dirty()
        return item

    def delete(self, key, table_name: str):
        del self.data.tables[table_name].items[key]
        self._mark_dirty()

    def clear(self, table_name: str = None):
        self.data.tables[table_name].clear()
        self._mark_dirty()

    def update(self, key, value, table_name):
        self.data.tables[table_name].items[key].value = value
        self.data.tables[table_name].items[key].updated = datetime.now()
        self._mark_dirty()