"""Unit tests for `SqlAlchemyUnitOfWork` construction (composition-root wiring, R-24)."""

from unittest.mock import MagicMock

from infrastructure.db.sqlalchemy_unit_of_work import SqlAlchemyUnitOfWork


class TestInit:
    def test_wraps_the_given_engine_without_building_a_new_one(self) -> None:
        fake_engine = MagicMock()

        uow = SqlAlchemyUnitOfWork(fake_engine)

        assert uow._engine is fake_engine
        assert uow.active_connection is None

    def test_two_instances_from_the_same_engine_have_independent_active_connection(self) -> None:
        fake_engine = MagicMock()

        first = SqlAlchemyUnitOfWork(fake_engine)
        second = SqlAlchemyUnitOfWork(fake_engine)
        first.active_connection = MagicMock()

        assert second.active_connection is None
