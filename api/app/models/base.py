from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

SCHEMA = "dora"

# Explicit names for any constraint or index the models don't name themselves,
# so autogenerate and the hand-written migrations agree.
NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ix": "ix_%(table_name)s_%(column_0_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA, naming_convention=NAMING_CONVENTION)
