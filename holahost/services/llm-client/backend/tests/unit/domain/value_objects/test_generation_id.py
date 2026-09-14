import uuid

from domain.value_objects.generation_id import GenerationId


class TestGenerationId:
    def test_new_generates_a_uuid(self) -> None:
        generation_id = GenerationId.new()
        assert isinstance(generation_id, uuid.UUID)
        assert isinstance(generation_id, GenerationId)

    def test_new_generates_distinct_ids(self) -> None:
        assert GenerationId.new() != GenerationId.new()
