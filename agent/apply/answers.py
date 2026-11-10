"""Decide what to put in each form field, using only your profile and resume.

Claude reads the form's questions and your profile and proposes answers.
Then plain code double-checks every proposed answer:
- a choice answer must be exactly one of the form's options;
- a typed answer must use only words that appear in your profile/resume;
- some questions are ALWAYS left for you, no matter what Claude says:
  essays, consents/agreements/signatures, salary, and file uploads other
  than your resume.
"""

import re
from dataclasses import dataclass, field

import yaml


@dataclass
class Question:
    key: str                  # the field's id/name on the page
    label: str                # the question text
    kind: str                 # text, textarea, select, combobox, radio, checkbox, file
    options: list = field(default_factory=list)
    required: bool = False


CHOICE_KINDS = {"select", "combobox", "radio", "checkbox"}

# Questions the agent never answers for you, even if it could.
ALWAYS_YOURS = re.compile(
    r"consent|agree|acknowledg|certif|attest|signature|sign here|terms|privacy|"
    r"salary|compensation|pay expectation|desired pay|referr|relative|family member|"
    r"\bwhy (do|are|would) you\b|\btell us\b|\bdescribe\b|\bexplain\b|cover letter",
    re.I,
)

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "leave_for_student": {"type": "boolean"},
                    "answer": {"type": "string", "description": "Empty if leave_for_student"},
                },
                "required": ["key", "leave_for_student", "answer"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["answers"],
    "additionalProperties": False,
}

ANSWER_PROMPT = """You fill in internship application forms for a student, \
using ONLY the facts in their profile and resume. Never guess or invent.

For each question, either answer it or set leave_for_student = true.
- Choice questions (select, combobox, radio, checkbox): the answer must be \
copied EXACTLY from that question's options. Pick the option that matches \
the profile's fact (e.g. profile gpa "3.80" -> option "3.5 - 4.0").
- Text questions: build the answer only from profile/resume values \
(e.g. "December 2027", "Virginia Commonwealth University").
- Leave it for the student when: the profile has no clear answer (blank \
values are left out of the profile on purpose); it's an essay, "why", or \
open-ended question; it's a consent, agreement, certification, or \
acknowledgment; it asks about pay; it asks about referrals or relatives.
- Work authorization, sponsorship, and self-identification (gender, race, \
veteran, disability): answer ONLY if the profile states it, and pick the \
matching option.
Return one entry for every question key."""


def _words(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def validate(question, answer, allowed_words):
    """Return the cleaned answer if it's safe to use, else None."""
    answer = (answer or "").strip()
    if not answer or ALWAYS_YOURS.search(question.label) or question.kind == "file":
        return None
    if question.kind in CHOICE_KINDS:
        # Must be one of the options (ignoring upper/lower case).
        for option in question.options:
            if option.strip().lower() == answer.lower():
                return option
        return None
    if question.kind in ("text", "textarea"):
        # Every word must come from the profile or resume. Stops inventions.
        return answer if _words(answer) <= allowed_words else None
    return None


def plan_answers(claude, model, profile, resume_text, questions, effort="low"):
    """Return {question key: answer} for the questions that can safely be
    filled. Everything else is left for you."""
    askable = [q for q in questions if q.kind != "file" and not ALWAYS_YOURS.search(q.label)]
    if not askable:
        return {}
    listing = yaml.safe_dump(
        [{"key": q.key, "question": q.label, "type": q.kind,
          **({"options": q.options} if q.options else {})} for q in askable],
        sort_keys=False, allow_unicode=True,
    )
    result = claude.ask(
        model, ANSWER_PROMPT,
        f"<profile>\n{yaml.safe_dump(profile, sort_keys=False, allow_unicode=True)}</profile>\n\n"
        f"<resume>\n{resume_text}\n</resume>\n\n<questions>\n{listing}</questions>",
        ANSWER_SCHEMA, effort=effort,
    )
    allowed = _words(" ".join(profile.values()) + " " + resume_text)
    by_key = {q.key: q for q in askable}
    answers = {}
    for item in result["answers"]:
        q = by_key.get(item["key"])
        if q is None or item["leave_for_student"]:
            continue
        safe = validate(q, item["answer"], allowed)
        if safe is not None:
            answers[q.key] = safe
    return answers
