from infrastructure.sample.source import S3SampleGuidebookSource


class _FakeBody:
    def read(self) -> bytes:
        return b"sample-guidebook-bytes"


class _FakeS3:
    def __init__(self) -> None:
        self.requested: list[tuple[str, str]] = []

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, _FakeBody]:
        self.requested.append((Bucket, Key))
        return {"Body": _FakeBody()}


def test_s3_source_reads_object_bytes() -> None:
    s3 = _FakeS3()
    source = S3SampleGuidebookSource(s3, bucket="holahost-frontend", key="config/sample_guidebook.md")
    assert source.read() == b"sample-guidebook-bytes"
    assert s3.requested == [("holahost-frontend", "config/sample_guidebook.md")]
