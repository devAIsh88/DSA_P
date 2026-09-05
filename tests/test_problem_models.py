from app.models.problem import Problem
from app.models.skill import Skill
from app.models.test_case import TestCase


def test_problem_catalog_models_have_expected_columns_and_foreign_keys() -> None:
    assert set(Skill.__table__.columns.keys()) == {
        "id",
        "name",
        "parent_skill_id",
        "description",
        "difficulty_range",
    }
    assert set(Problem.__table__.columns.keys()) == {
        "id",
        "title",
        "description",
        "difficulty",
        "source",
        "topic",
        "subtopic",
        "constraints",
        "input_format",
        "output_format",
        "expected_complexity",
        "target_track",
        "created_at",
    }
    assert set(TestCase.__table__.columns.keys()) == {
        "id",
        "problem_id",
        "input",
        "expected_output",
        "is_sample",
        "is_hidden",
        "weight",
    }

    assert {foreign_key.target_fullname for foreign_key in Skill.__table__.foreign_keys} == {
        "skills.id"
    }
    assert {foreign_key.target_fullname for foreign_key in TestCase.__table__.foreign_keys} == {
        "problems.id"
    }
    test_case_foreign_key = next(iter(TestCase.__table__.foreign_keys))
    assert test_case_foreign_key.ondelete == "CASCADE"
