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
    kind: str                 # text, textarea, select, combobox, dropdown, prompt, radio, checkbox, file
    options: list = field(default_factory=list)
    required: bool = False


# "dropdown" and "prompt" are Workday's dropdowns and type-to-search boxes.
CHOICE_KINDS = {"select", "combobox", "dropdown", "prompt", "radio", "checkbox"}

# Questions the agent never answers for you, even if it could.
ALWAYS_YOURS = re.compile(
    r"consent|agree|acknowledg|certif|attest|signature|sign here|terms|privacy|"
    r"salary|compensation|pay expectation|desired pay|referr|relative|family member|"
    r"\bwhy (do|are|would) you\b|\btell us\b|\bdescribe\b|\bexplain\b|cover letter",
    re.I,
)

# Voluntary self-identification questions. These are answered ONLY by the
# code below, on your computer: neither your answers nor these questions
# are ever sent to Claude.
SENSITIVE = [
    # (profile key, words that identify the question). Checked in this order,
    # so "Race/Ethnicity (incl. Hispanic)" counts as the race question.
    ("race_ethnicity", re.compile(r"\brace\b", re.I)),
    ("hispanic_or_latino", re.compile(r"hispanic|latin[oax]", re.I)),
    ("race_ethnicity", re.compile(r"ethnic", re.I)),
    ("gender", re.compile(r"\bgender\b|\bsex\b", re.I)),
    ("veteran_status", re.compile(r"veteran|military|armed forces", re.I)),
    ("disability_status", re.compile(r"disabilit", re.I)),
    ("pronouns", re.compile(r"pronoun", re.I)),
]
SENSITIVE_KEYS = {key for key, _ in SENSITIVE}
# Other personal questions with no profile answer: always left for you, never sent.
OTHER_PERSONAL = re.compile(r"sexual orientation|transgender|lgbt", re.I)

DECLINE_WORDS = re.compile(
    r"decline|prefer not|(don.?t|do not) (wish|want)|choose not|not to (answer|disclose|say)|"
    r"not (disclose|answer|specified)|rather not",
    re.I,
)

# Yes/no-style self-ID questions, where "No, I am not a protected veteran" and
# "I am not a veteran" mean the same thing on different forms.
YES_NO_KEYS = {"veteran_status", "disability_status", "hispanic_or_latino"}
NEGATIVE_WORDS = re.compile(r"^\s*no\b|\bnot\b|\b(do not|don.?t|does not|doesn.?t)\b", re.I)


def _is_negative(text):
    return bool(NEGATIVE_WORDS.search(text)) and not DECLINE_WORDS.search(text)


def sensitive_key(question):
    """Which profile answer a self-identification question needs, or None."""
    for key, pattern in SENSITIVE:
        if pattern.search(question.label):
            return key
    return None


def is_personal(question):
    return sensitive_key(question) is not None or bool(OTHER_PERSONAL.search(question.label))


def match_sensitive(question, profile):
    """Pick the form's option for a self-identification question using plain
    text matching (no AI). Returns the option, or None to leave it for you."""
    key = sensitive_key(question)
    answer = profile.get(key, "").strip() if key else ""
    # Checkboxes (like Workday's disability form) are always left for you: one
    # wrong tick on a form like that is too easy to miss.
    if not answer or question.kind not in CHOICE_KINDS - {"checkbox"} or not question.options:
        return None
    wanted = answer.lower()
    # 1. Exact match, ignoring case.
    for option in question.options:
        if option.strip().lower() == wanted:
            return option
    # 2. "Decline to self-identify" is worded differently on every form.
    if DECLINE_WORDS.search(answer):
        return next((o for o in question.options if DECLINE_WORDS.search(o)), None)
    # 3. One contains the other, e.g. "Black" vs "Black or African American".
    #    Only if exactly one option matches, so we never guess between two.
    hits = [o for o in question.options
            if not DECLINE_WORDS.search(o) and (wanted in o.lower() or o.lower() in wanted)]
    if len(hits) == 1:
        return hits[0]
    # 4. Yes/no questions worded differently: a "no" answer picks the form's
    #    one "no" option ("I am not a protected veteran" -> "I am not a veteran").
    #    If the form has two different "no" options, it's left for you.
    if key in YES_NO_KEYS and _is_negative(answer):
        negatives = [o for o in question.options if _is_negative(o)]
        if len(negatives) == 1:
            return negatives[0]
    return None


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
- Work authorization and sponsorship: answer ONLY if the profile states it, \
and pick the matching option.
Return one entry for every question key."""


def _words(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def validate(question, answer, allowed_words):
    """Return the cleaned answer if it's safe to use, else None."""
    answer = (answer or "").strip()
    if not answer or ALWAYS_YOURS.search(question.label) or question.kind == "file":
        return None
    if question.kind in CHOICE_KINDS and question.options:
        # Must be one of the options (ignoring upper/lower case).
        for option in question.options:
            if option.strip().lower() == answer.lower():
                return option
        return None
    if question.kind in ("text", "textarea") or question.kind in CHOICE_KINDS:
        # Typed answers, and search boxes whose choices we can't see ahead of
        # time (the filler then has to find an option matching this exactly).
        # Every word must come from the profile or resume. Stops inventions.
        return answer if _words(answer) <= allowed_words else None
    return None


def plan_answers(claude, model, profile, resume_text, questions, effort="low"):
    """Return {question key: answer} for the questions that can safely be
    filled. Everything else is left for you."""
    answers = {}
    # Self-identification questions: matched by code only, never sent to Claude.
    for q in questions:
        if is_personal(q):
            choice = match_sensitive(q, profile)
            if choice is not None:
                answers[q.key] = choice

    askable = [q for q in questions
               if q.kind != "file" and not ALWAYS_YOURS.search(q.label) and not is_personal(q)]
    if not askable:
        return answers
    # Your self-identification answers are removed before anything is sent.
    shareable = {k: v for k, v in profile.items() if k not in SENSITIVE_KEYS}
    listing = yaml.safe_dump(
        [{"key": q.key, "question": q.label, "type": q.kind,
          **({"options": q.options} if q.options else {})} for q in askable],
        sort_keys=False, allow_unicode=True,
    )
    result = claude.ask(
        model, ANSWER_PROMPT,
        f"<profile>\n{yaml.safe_dump(shareable, sort_keys=False, allow_unicode=True)}</profile>\n\n"
        f"<resume>\n{resume_text}\n</resume>\n\n<questions>\n{listing}</questions>",
        ANSWER_SCHEMA, effort=effort,
    )
    allowed = _words(" ".join(shareable.values()) + " " + resume_text)
    by_key = {q.key: q for q in askable}
    for item in result["answers"]:
        q = by_key.get(item["key"])
        if q is None or item["leave_for_student"]:
            continue
        safe = validate(q, item["answer"], allowed)
        if safe is not None:
            answers[q.key] = safe
    return answers
