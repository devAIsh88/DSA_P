from app.models.user import User


def test_user_model_has_expected_table_and_columns() -> None:
    assert User.__tablename__ == "users"
    assert set(User.__table__.columns.keys()) == {"id", "created_at", "updated_at"}

