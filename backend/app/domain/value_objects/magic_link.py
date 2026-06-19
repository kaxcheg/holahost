from __future__ import annotations

from dataclasses import dataclass

from pydantic import SecretStr


@dataclass(frozen=True)
class MagicLink:
    """Magic-link token wrapping a secret (spec §7.2.1).

    The value is held in ``pydantic.SecretStr`` so it never leaks via ``repr``, logs, or
    tracebacks. Length/charset are enforced by the generator (``MagicLinkGenerator``), not here.

    Args:
        value: The token, wrapped in ``SecretStr``.

    :raises ValueError: If the wrapped secret is empty.
    """

    value: SecretStr

    def __post_init__(self) -> None:
        """Validate that the secret is non-empty.

        An empty/invalid token is an invalid credential, so this raises a plain ``ValueError`` (not
        a ``DomainValidationError``): the use case wraps construction in ``magic_link_validation()``
        and maps it to 401 ``InvalidMagicLinkError`` (§9.8), consistent with the unknown/expired
        cases — not a 422 payload error. Plain ``ValueError`` also keeps the failure safe: an
        unwrapped construction surfaces as 500, never a silent mis-mapped 422.

        :raises ValueError: If the wrapped secret is empty.
        """
        if not self.value.get_secret_value():
            raise ValueError("MagicLink: empty value")
