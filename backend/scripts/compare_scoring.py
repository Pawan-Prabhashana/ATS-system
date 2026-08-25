"""Side-by-side: render+images scoring vs pdf_direct scoring (Phase 16).

Answers "does the scoring hold if we send the PDF straight to Claude instead of
rendering it to images?" — scores each CV BOTH ways with the SAME rubric and
prints per-criterion scores, overall, recommendation, and the delta.

OPT-IN and LIVE: it makes real Anthropic API calls, so it is gated.

    RUN_SCORING_COMPARE=1 ANTHROPIC_API_KEY=sk-ant-... \
        python -m scripts.compare_scoring [extra_cv.pdf ...]

By default it runs the bundled sample CVs against BOTH a content-only rubric
(rubric.json) and a creative/visual rubric (rubric_design.json, which sets
requires_visual_review=true — the case most worth confirming). Extra CV paths
given as args are added to the set.

COST: each CV is scored twice per rubric (render + pdf_direct) = 2 live calls.
pdf_direct sends the whole PDF as input (more input tokens than a text+images
prompt), so expect a few cents total on Sonnet for the sample set — more for
large/real CVs. Don't run it in a loop.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from app.config import settings
from app.evaluation.anthropic_native import AnthropicEvaluator
from app.models import Evaluation, Rubric
from app.parsing import parse_cv_file

SAMPLE = settings.sample_data_dir
DEFAULT_CVS = [SAMPLE / "sample_cv_text.pdf", SAMPLE / "sample_cv_text_2.pdf"]
JOB_DESCRIPTION = (
    "We are hiring for a role that values strong fundamentals, clear communication, "
    "and relevant hands-on experience. For creative roles, visual craft and layout matter."
)


def _score_both(cv_path: Path, rubric: Rubric) -> tuple[Evaluation, Evaluation]:
    ev = AnthropicEvaluator()
    # render+images: parse WITH rendering, evaluate the normal way.
    _cand_r, parsed_render = parse_cv_file(cv_path, render_images=True)
    render_eval = ev.evaluate(parsed_render, JOB_DESCRIPTION, rubric)
    # pdf_direct: no rendering; hand the PDF bytes straight to Claude.
    _cand_p, parsed_direct = parse_cv_file(cv_path, render_images=False)
    direct_eval = ev.evaluate(parsed_direct, JOB_DESCRIPTION, rubric, pdf_bytes=cv_path.read_bytes())
    return render_eval, direct_eval


def _print_comparison(cv_path: Path, rubric_name: str, render: Evaluation, direct: Evaluation) -> None:
    print("\n" + "=" * 72)
    print(f"CV: {cv_path.name}    rubric: {rubric_name}")
    print("=" * 72)
    print(f"{'criterion':<28}{'render':>10}{'pdf_direct':>14}{'delta':>10}")
    print("-" * 72)
    r_by = {c.criterion_name: c.score for c in render.criterion_scores}
    d_by = {c.criterion_name: c.score for c in direct.criterion_scores}
    for name in sorted(set(r_by) | set(d_by)):
        r, d = r_by.get(name), d_by.get(name)
        delta = f"{(d - r):+.1f}" if (r is not None and d is not None) else "—"
        print(f"{name[:27]:<28}{_fmt(r):>10}{_fmt(d):>14}{delta:>10}")
    print("-" * 72)
    print(f"{'OVERALL':<28}{render.overall_score:>10.1f}{direct.overall_score:>14.1f}{direct.overall_score - render.overall_score:>+10.1f}")
    print(f"{'recommendation':<28}{render.recommendation.value:>10}{direct.recommendation.value:>14}"
          f"{'  (same)' if render.recommendation == direct.recommendation else '  CHANGED':>10}")


def _fmt(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}"


def main(argv: list[str]) -> int:
    if not os.getenv("RUN_SCORING_COMPARE"):
        print("Opt-in only. Re-run with RUN_SCORING_COMPARE=1 (and a real ANTHROPIC_API_KEY).")
        return 0
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set — this comparison makes real Claude calls.")
        return 1

    cvs = list(DEFAULT_CVS) + [Path(a) for a in argv]
    cvs = [c for c in cvs if c.exists()]
    if not cvs:
        print("No CV files found. Point it at some PDFs (args) or generate the samples.")
        return 1

    rubrics = {
        "content-only": Rubric.model_validate_json((SAMPLE / "rubric.json").read_text()),
        "creative/visual": Rubric.model_validate_json((SAMPLE / "rubric_design.json").read_text()),
    }

    print(f"Scoring {len(cvs)} CV(s) x {len(rubrics)} rubric(s), each BOTH ways. "
          f"This makes {2 * len(cvs) * len(rubrics)} live Anthropic calls.")
    for cv in cvs:
        for rubric_name, rubric in rubrics.items():
            try:
                render, direct = _score_both(cv, rubric)
                _print_comparison(cv, rubric_name, render, direct)
            except Exception as exc:  # noqa: BLE001 - keep going across the set
                print(f"\n[skip] {cv.name} / {rubric_name}: {type(exc).__name__}: {exc}")
    print("\nDone. Compare the deltas — small, stable deltas mean pdf_direct holds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
