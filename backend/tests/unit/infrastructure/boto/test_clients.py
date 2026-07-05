from infrastructure.boto.clients import make_s3_client, make_secrets_client


def test_make_secrets_client_uses_explicit_region() -> None:
    assert make_secrets_client("eu-west-1").meta.region_name == "eu-west-1"


def test_make_s3_client_uses_explicit_region() -> None:
    assert make_s3_client("eu-west-1").meta.region_name == "eu-west-1"
