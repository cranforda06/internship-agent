"""Fill a Lever application form (never submits it).

Lever forms are plain HTML, so we read the questions straight off the page:
each question sits in an ".application-question" block with a label and
its inputs (text boxes, dropdowns, radio buttons, checkboxes).
"""

import re

from agent.apply.answers import Question

URL_PATTERN = re.compile(r"jobs\.lever\.co/([\w-]+)/([0-9a-f-]{36})")

READ_FORM = """() => {
  const out = [];
  document.querySelectorAll('.application-question').forEach(block => {
    const labelEl = block.querySelector('.application-label') || block;
    const label = labelEl.innerText.split('\\n')[0].replace('✱', '').trim();
    const required = !!block.querySelector('.required, [required]');
    const inputs = [...block.querySelectorAll('input:not([type=hidden]), textarea, select')];
    if (!inputs.length) return;
    const first = inputs[0];
    let kind = first.tagName === 'SELECT' ? 'select'
             : first.tagName === 'TEXTAREA' ? 'textarea'
             : ['radio', 'checkbox', 'file'].includes(first.type) ? first.type : 'text';
    let options = [];
    if (kind === 'select') options = [...first.options].map(o => o.text.trim()).filter(t => t && !/^select/i.test(t));
    if (kind === 'radio' || kind === 'checkbox') options = inputs.map(i => i.value);
    out.push({key: first.name, label, kind, options, required});
  });
  return out;
}"""


def can_handle(url):
    return bool(URL_PATTERN.search(url or ""))


def apply_url(url):
    company, job_id = URL_PATTERN.search(url).groups()
    return f"https://jobs.lever.co/{company}/{job_id}/apply"


def open_and_read(page, url):
    """Open the form and return its questions."""
    page.goto(apply_url(url), wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector("form .application-question", timeout=30000)
    return [Question(**q) for q in page.evaluate(READ_FORM) if q["key"]]


def fill(page, questions, answers, resume_pdf, log=print):
    """Fill the already-open form. Returns the list of questions left for you."""
    left = []
    resume = page.locator('input[name="resume"]')
    if resume.count():
        resume.set_input_files(resume_pdf)
        log("  ✓ uploaded tailored resume PDF")
        # Lever reads the resume and pre-fills some boxes; give it a moment,
        # then our answers overwrite anything it guessed.
        page.wait_for_timeout(3000)

    for q in questions:
        if q.kind == "file":
            continue
        answer = answers.get(q.key)
        try:
            if answer is None:
                if q.required:
                    left.append(q)
            elif q.kind in ("text", "textarea"):
                page.locator(f'[name="{q.key}"]').first.fill(answer)
            elif q.kind == "select":
                page.locator(f'select[name="{q.key}"]').select_option(label=answer)
            elif q.kind in ("radio", "checkbox"):
                page.locator(f'input[name="{q.key}"][value="{answer}"]').check()
        except Exception as e:
            log(f"  ! couldn't fill '{q.label[:50]}': {e.__class__.__name__}")
            left.append(q)
    return left
