from __future__ import annotations

from pydantic import SecretStr

from domain.value_objects.ip_hash import IpHash
from infrastructure.common.sha256_ip_hasher import Sha256IpHasher

_SALT = SecretStr("test-salt")


def test_hash_matches_known_vector() -> None:
    hasher = Sha256IpHasher(_SALT)
    result = hasher.hash("1.2.3.4")
    assert isinstance(result, IpHash)
    assert result.value == "44501e19281a9814b8df91ce222b74c080a19424107e3df6351a8da2282cc8e2"


def test_hash_is_deterministic_and_ip_sensitive() -> None:
    hasher = Sha256IpHasher(_SALT)
    assert hasher.hash("1.2.3.4").value == hasher.hash("1.2.3.4").value
    assert (
        hasher.hash("9.9.9.9").value
        == "afb4e8f73d714690f3c54eee919b259d776e7c5f9699e2889541decf03f881ca"
    )
    assert hasher.hash("1.2.3.4").value != hasher.hash("9.9.9.9").value


def test_hash_is_salt_sensitive() -> None:
    a = Sha256IpHasher(SecretStr("salt-a")).hash("1.2.3.4").value
    b = Sha256IpHasher(SecretStr("salt-b")).hash("1.2.3.4").value
    assert a != b
