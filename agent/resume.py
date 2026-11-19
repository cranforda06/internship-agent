from pathlib import Path

TEMPLATE_MARKER = "REPLACE THIS TEMPLATE"


class ResumeError(Exception):
    pass


def load_resume(path):
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
    sections = {"Header": []}
    current = "Header"
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        else:
            sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}
