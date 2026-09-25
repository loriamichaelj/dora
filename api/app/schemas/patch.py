"""Base for PATCH bodies: partial updates with explicit-null handling.

A field left out of the body is untouched. A field sent as `null` clears it,
but only if the column is nullable; otherwise that's a 422.
"""

from typing import Any, ClassVar, Self

from pydantic import BaseModel, ConfigDict, model_validator


class PatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Fields that may be sent as null to clear them.
    nullable_fields: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _reject_null_for_required(self) -> Self:
        for name in self.model_fields_set:
            if getattr(self, name) is None and name not in self.nullable_fields:
                raise ValueError(f"'{name}' cannot be null")
        return self

    def changes(self) -> dict[str, Any]:
        """Only the fields the client actually sent."""
        return self.model_dump(exclude_unset=True)
