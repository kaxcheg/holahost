from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

EMBEDDING_DIM = 384


@dataclass(frozen=True, eq=False)
class Embedding:
    """384-dim L2-normalized float32 embedding vector (spec §7.2.4).

    Stored as a 1-D ``numpy`` array. Uses ``eq=False`` (identity equality): the default
    dataclass equality is ambiguous for ``ndarray`` fields and ``ndarray`` is unhashable;
    embedding equality is unused in the codebase (retrieval works on cosine similarity).

    Args:
        vector: 1-D array of shape ``(EMBEDDING_DIM,)``, dtype ``float32``, L2-normalized.

    :raises ValueError: If shape, dtype, or L2 norm is invalid.
    """

    vector: npt.NDArray[np.float32]

    def __post_init__(self) -> None:
        """Validate shape, dtype, finiteness, and L2 norm.

        :raises ValueError: If shape != ``(EMBEDDING_DIM,)``, dtype is not float32, the vector
            holds non-finite values (NaN/inf), or the L2 norm is not within ``1e-3`` of 1.0.
        """
        if self.vector.shape != (EMBEDDING_DIM,):
            raise ValueError(
                f"Embedding: expected shape ({EMBEDDING_DIM},), got {self.vector.shape}"
            )
        if self.vector.dtype != np.dtype(np.float32):
            raise ValueError(f"Embedding: expected float32, got {self.vector.dtype}")
        if not bool(np.isfinite(self.vector).all()):
            raise ValueError("Embedding: vector contains non-finite values (NaN or inf)")
        norm = float(np.linalg.norm(self.vector))
        if abs(norm - 1.0) > 1e-3:
            raise ValueError(f"Embedding: vector must be L2-normalized (norm={norm})")

    @classmethod
    def from_bytes(cls, b: bytes) -> Embedding:
        """Reconstruct an embedding from a raw float32 byte buffer.

        Args:
            b: Raw bytes of ``EMBEDDING_DIM`` little-endian float32 values.

        Returns:
            The reconstructed, validated embedding.

        :raises ValueError: If the buffer length/contents do not form a valid embedding.
        """
        return cls(vector=np.frombuffer(b, dtype=np.float32))

    def to_bytes(self) -> bytes:
        """Serialize the vector to a raw float32 byte buffer.

        Returns:
            The vector's raw bytes (``EMBEDDING_DIM * 4`` bytes).
        """
        return self.vector.tobytes()
