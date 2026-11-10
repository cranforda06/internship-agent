"""Loads your master resume from a Markdown (.md) or plain text file."""

from pathlib import Path

# This phrase appears only in the starter template. If we see it, the user
# hasn't pasted their real resume in yet.
TEMPLATE_MARKER = "REPLACE THIS TEMPLATE"


class ResumeError(Exception):
    """Raised when the resume file is missing or still the template."""


def load_resume(path):
    """Return the full text of your resume.

    Raises ResumeError with a friendly message if something is wrong.
    """
    path = Path(path)
    if not path.exists():
        raise ResumeError(f"No resume found at {path}. Create it and paste your resume in.")

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ResumeError(f"{path} is empty. Paste your resume into it.")
    if TEMPLATE_MARKER in text:
        raise ResumeError(f"{path} is still the template. Replace it with your real resume.")
    return text


def split_sections(text):
    """Split a resume into sections using its "## Heading" lines.

    Example: "## Skills\\nPython, SQL" becomes {"Skills": "Python, SQL"}.
    Anything before the first "##" (your name and contact info) goes under
    the key "Header". Phase 3 uses this to reorder sections per job.
    """
    sections = {"Header": []}
    current = "Header"
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        else:
            sections[current].append(line)
    # Join each section's lines back into one block of text.
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}
