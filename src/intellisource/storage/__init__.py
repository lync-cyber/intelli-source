"""Storage layer public surface.

``EMBEDDING_DIM`` is re-exported here so higher layers can validate vector
dimensions without importing ``storage.models`` directly (ORM boundary —
higher layers reach models only through this package or repositories).
"""

from intellisource.storage.models import EMBEDDING_DIM

__all__ = ["EMBEDDING_DIM"]
