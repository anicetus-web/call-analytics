from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm.exc import DetachedInstanceError


class ReprMixin:
    """
    Provides __repr__ for all models.
    Define __repr_fields__ = ("field1", "field2") on the model to control output.
    Mapper introspection result is cached per class on first __repr__ call.
    """
    __repr_fields__: tuple[str, ...] = ()
    _repr_fields_cache: tuple[str, ...] | None = None

    @classmethod
    def _resolved_repr_fields(cls) -> tuple[str, ...]:
        if cls._repr_fields_cache is None:
            if cls.__repr_fields__:
                cls._repr_fields_cache = cls.__repr_fields__
            else:
                insp = sa_inspect(cls)
                cls._repr_fields_cache = tuple(col.key for col in insp.primary_key)
        return cls._repr_fields_cache

    def __repr__(self) -> str:
        fields = self._resolved_repr_fields()
        try:
            vals = {f: getattr(self, f) for f in fields}
        except DetachedInstanceError:
            vals = {"<detached>": "attributes not loaded"}
        return f"<{self.__class__.__name__}({vals})>"


class Base(ReprMixin, DeclarativeBase):
    pass
