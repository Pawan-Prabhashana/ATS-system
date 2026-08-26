"""The "score visual design" toggle (``requires_visual_review``) must guarantee
the visual criterion exists — so the visual design score is always evaluated and
shown, never silently dropped because a rubric forgot to list it.
"""
from app.models import Rubric, RubricCriterion
from app.models.schemas import VISUAL_CRITERION_NAME


def _names(r: Rubric) -> list[str]:
    return [c.name for c in r.criteria]


def test_toggle_on_injects_visual_criterion_when_missing():
    r = Rubric(
        job_title="Graphic Designer",
        requires_visual_review=True,
        criteria=[RubricCriterion(name="Tooling", weight=2.0)],
    )
    assert VISUAL_CRITERION_NAME in _names(r)
    # Injected at the front so it reads first in the breakdown.
    assert r.criteria[0].name == VISUAL_CRITERION_NAME
    assert r.criteria[0].weight > 0


def test_toggle_on_does_not_duplicate_existing_visual_criterion():
    r = Rubric(
        job_title="Graphic Designer",
        requires_visual_review=True,
        criteria=[
            RubricCriterion(name="Visual hierarchy & layout", weight=3.0),
            RubricCriterion(name="Tooling", weight=2.0),
        ],
    )
    assert _names(r).count("Visual hierarchy & layout") == 1


def test_toggle_off_leaves_criteria_untouched():
    r = Rubric(
        job_title="Backend Engineer",
        requires_visual_review=False,
        criteria=[RubricCriterion(name="Python & backend experience", weight=3.0)],
    )
    assert _names(r) == ["Python & backend experience"]


def test_design_in_name_is_not_treated_as_visual():
    # "Portfolio & design experience" mentions design but is NOT the visual
    # criterion — the visual score must still be injected.
    r = Rubric(
        job_title="Graphic Designer",
        requires_visual_review=True,
        criteria=[RubricCriterion(name="Portfolio & design experience", weight=3.0)],
    )
    assert VISUAL_CRITERION_NAME in _names(r)
    assert len(r.criteria) == 2
