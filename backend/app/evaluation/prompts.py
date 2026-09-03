"""Prompt templates for the real (vision+text) evaluator.

Kept separate from the HTTP/plumbing in ``real.py`` so the wording can be
iterated on independently. ``build_system_prompt`` embeds the exact rubric
criteria + weights and the required output schema so the model cannot invent
its own criteria or shape.
"""
from __future__ import annotations

import json

from app.models import Rubric

# The exact JSON shape we expect back. Mirrors app.models.Evaluation /
# CriterionScore. Shown to the model verbatim.
OUTPUT_SCHEMA_HINT = """\
{
  "criterion_scores": [
    {
      "criterion_name": "<must match one of the rubric criteria names exactly>",
      "score": <number 0-100>,
      "weight": <the weight given for that criterion below>,
      "evidence": "<a short quote or close paraphrase from the CV supporting the score>"
    }
    // ... exactly one object per rubric criterion, same order
  ],
  "overall_score": <number 0-100, the weight-weighted average of the scores>,
  "recommendation": "<one of: shortlist | borderline | reject>",
  "summary": "<2-4 sentence overall justification>"
}"""


def _format_criteria(rubric: Rubric) -> str:
    lines = []
    for c in rubric.criteria:
        desc = f" — {c.description}" if c.description else ""
        lines.append(f'  - "{c.name}" (weight {c.weight}){desc}')
    return "\n".join(lines)


def build_system_prompt(job_description: str, rubric: Rubric) -> str:
    """Assemble the system prompt: role, rubric+weights, scoring rules, schema.

    The visual-hierarchy instruction is included **only** when
    ``rubric.requires_visual_review`` is True. When False, the prompt does not
    mention layout/formatting/images at all — the model scores content match
    only, and no image payload is sent alongside this prompt.
    """
    total_weight = sum(c.weight for c in rubric.criteria)
    job_title = rubric.job_title or "the role"
    visual = rubric.requires_visual_review

    if visual:
        intro = (
            "You are given the CV's extracted text (for precise wording and\n"
            "keywords) AND images of the CV pages (for visual hierarchy: layout,\n"
            "formatting, structure, and section design). Use BOTH: the text for\n"
            "exact content, the images for how well the document is presented."
        )
        evidence_clause = (
            "quote or closely paraphrase the specific text, or describe the "
            "specific\n   visual detail (from the page images), that justifies "
            "the score"
        )
    else:
        intro = (
            "You are given the CV's extracted text (for precise wording and\n"
            "keywords). Score the candidate on CONTENT match to the job and\n"
            "rubric only. No page images are provided and document layout/\n"
            "formatting is NOT part of this assessment — do not speculate about it."
        )
        evidence_clause = (
            "quote or closely paraphrase the specific text that justifies the score"
        )

    steps = [
        "1. Score EACH rubric criterion independently on a 0-100 scale. Judge each\n"
        "   on its own merits; do not let a strong (or weak) area bleed into others.",
        f"2. For each criterion, cite concrete evidence: {evidence_clause}.\n"
        "   No evidence => low confidence => lower score.",
    ]
    if visual:
        steps.append(
            "3. Treat visual hierarchy / formatting quality as its own signal "
            "wherever\n   the rubric includes a presentation-related criterion — "
            "assess it from the\n   page images, and do NOT silently fold it into "
            "a content criterion."
        )
    next_n = len(steps) + 1
    steps.append(
        f"{next_n}. Compute overall_score as the WEIGHTED AVERAGE of the criterion "
        "scores using\n   exactly the weights listed above:\n"
        f"       overall_score = sum(score_i * weight_i) / {total_weight}\n"
        "   Be consistent — do not eyeball it; use the weights."
    )
    steps.append(
        f"{next_n + 1}. Map overall_score to a recommendation:\n"
        '       >= 70  -> "shortlist"\n'
        '       50-69  -> "borderline"\n'
        '       <  50  -> "reject"'
    )

    how_to_score = "\n".join(steps)

    return f"""\
You are an expert technical recruiter screening a candidate's CV for {job_title}.
{intro}

=== JOB DESCRIPTION ===
{job_description.strip()}

=== SCORING RUBRIC (criteria and weights) ===
{_format_criteria(rubric)}

Total weight across criteria: {total_weight}.

=== HOW TO SCORE ===
{how_to_score}

=== OUTPUT FORMAT ===
Return ONLY a single JSON object — no markdown fences, no prose before or after.
It must match this schema exactly (one criterion_scores entry per rubric
criterion, names matching exactly, in the same order):

{OUTPUT_SCHEMA_HINT}
"""


def build_retry_message(error: str) -> str:
    """Corrective follow-up sent after an invalid response."""
    return (
        f"Your last response was not valid according to the required schema: "
        f"{error}\n\n"
        "Return ONLY a single valid JSON object matching the schema exactly — "
        "no markdown code fences, no commentary, one entry per rubric criterion "
        "with names matching exactly. Do not include anything except the JSON."
    )


def build_user_text(parsed_cv_text: str, include_images: bool = False) -> str:
    """The text portion of the user message (extracted CV text).

    ``include_images`` tells the phrasing whether page images are being attached
    to this message, so the prompt never references images that aren't there.
    """
    text = parsed_cv_text.strip()
    if not text:
        if include_images:
            return (
                "The CV's extracted text layer was essentially empty (likely a "
                "scanned/image-only CV). Rely on the page images below for all "
                "content and formatting judgements."
            )
        return (
            "The CV's extracted text layer was essentially empty (likely a "
            "scanned/image-only CV) and no page images were provided for this "
            "rubric. Base your assessment on whatever limited text is available "
            "and score conservatively where evidence is missing."
        )
    trailer = (
        "\nPage images follow for visual/formatting assessment." if include_images else ""
    )
    return (
        "=== EXTRACTED CV TEXT (verbatim) ===\n"
        f"{text}\n"
        "=== END EXTRACTED CV TEXT ==="
        f"{trailer}"
    )


def build_pdf_direct_user_text(include_images: bool = False) -> str:
    """User message when the CV is attached as a native PDF document (pdf_direct)
    and no separate extracted text is provided — the model reads the PDF itself.
    ``include_images`` here means the rubric wants visual/design assessment."""
    if include_images:
        return (
            "The candidate's CV is attached as a PDF document. Read the ENTIRE "
            "document carefully — both its text (skills, experience, wording) AND "
            "its visual layout, typography, and formatting — and score it against "
            "the rubric. Everything you need is in the attached PDF; do not treat "
            "any section as missing."
        )
    return (
        "The candidate's CV is attached as a PDF document. Read the ENTIRE "
        "document carefully and score it against the rubric on content match. "
        "Everything you need is in the attached PDF; do not treat any section as "
        "missing."
    )


def dumps_compact(obj) -> str:
    """Helper for tests/logging: stable compact JSON."""
    return json.dumps(obj, separators=(",", ":"), sort_keys=True)
