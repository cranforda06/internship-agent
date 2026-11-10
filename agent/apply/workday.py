"""Assisted filling for Workday applications (never submits, never clicks Next).

Workday applications need a separate account at each company, and they're
spread over several pages. So this works side by side with you:

  1. You click Apply, choose "Autofill with Resume", and sign in or create
     the account yourself.
  2. On each page, press Enter in the terminal. The agent reads that page's
     questions, uploads your tailored resume if the page asks for it, and
     fills in what it can from your profile.
  3. You check the page and click Next yourself. Repeat until the Review
     page, where YOU click Submit.

The agent only fills EMPTY fields, so it never overwrites what Workday or
you already entered. It reads questions off the page itself (labels, options),
so it works across companies even though each one's questions differ.
"""

from agent.apply.answers import Question, plan_answers

# Reads every visible form field on the page and tags each with a
# data-ia-key attribute so we can find it again to fill it.
READ_PAGE = r"""() => {
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const clean = t => (t || '').replace(/\s+/g, ' ').trim();
  const textOf = el => el ? clean(el.innerText || el.textContent) : '';
  const fieldLabel = el => {
    const box = el.closest('[data-automation-id^="formField"], fieldset');
    const lab = box && box.querySelector('label, legend');
    return lab ? textOf(lab) : '';
  };
  const ownLabel = el => {
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) return textOf(l);
    }
    const by = el.getAttribute('aria-labelledby');
    if (by) {
      const t = clean(by.split(' ').map(id => textOf(document.getElementById(id))).join(' '));
      if (t) return t;
    }
    return clean(el.getAttribute('aria-label'));
  };
  const isRequired = (el, label) => /\*/.test(label) || el.getAttribute('aria-required') === 'true' || el.required;

  document.querySelectorAll('[data-ia-key]').forEach(e => e.removeAttribute('data-ia-key'));
  const out = [], radioGroups = {};
  let n = 0;
  for (const el of document.querySelectorAll('input, textarea, button[aria-haspopup="listbox"]')) {
    const type = (el.type || '').toLowerCase();
    if (type === 'file') {                         // file inputs are often hidden on purpose
      const key = 'k' + n++;
      el.setAttribute('data-ia-key', key);
      out.push({key, label: fieldLabel(el) || ownLabel(el) || 'File upload', kind: 'file',
                options: [], required: false, filled: false});
      continue;
    }
    if (!visible(el) && type !== 'radio' && type !== 'checkbox') continue;
    if (el.tagName === 'BUTTON') {                 // Workday dropdown
      const label = fieldLabel(el) || ownLabel(el);
      const current = textOf(el);
      const key = 'k' + n++;
      el.setAttribute('data-ia-key', key);
      out.push({key, label, kind: 'dropdown', options: [], required: isRequired(el, label),
                filled: !!current && !/^select one/i.test(current)});
      continue;
    }
    if (['hidden', 'submit', 'button', 'reset', 'image'].includes(type)) continue;
    if (el.getAttribute('role') === 'spinbutton') continue;   // date parts: left for you
    if (type === 'radio') {
      const group = el.name || fieldLabel(el);
      if (!radioGroups[group]) {
        const key = 'k' + n++;
        const label = fieldLabel(el);
        radioGroups[group] = {key, label, kind: 'radio', options: [], required: isRequired(el, label),
                              filled: false};
        out.push(radioGroups[group]);
      }
      const g = radioGroups[group];
      el.setAttribute('data-ia-key', g.key + '-' + g.options.length);
      g.options.push(ownLabel(el));
      if (el.checked) g.filled = true;
      continue;
    }
    const key = 'k' + n++;
    el.setAttribute('data-ia-key', key);
    if (type === 'checkbox') {
      const label = ownLabel(el) || fieldLabel(el);
      out.push({key, label, kind: 'checkbox', options: [label], required: isRequired(el, label),
                filled: el.checked});
      continue;
    }
    const label = fieldLabel(el) || ownLabel(el);
    const isSearch = !!el.closest('[data-automation-id*="multiselect"], [data-automation-id*="Prompt"]')
                     || type === 'search';
    out.push({key, label, kind: isSearch ? 'prompt' : (el.tagName === 'TEXTAREA' ? 'textarea' : 'text'),
              options: [], required: isRequired(el, label), filled: !!clean(el.value)});
  }
  return out.map(q => ({...q, label: clean(q.label.replace(/\*/g, ''))}));
}"""


def _visible_options(page):
    options = page.locator('[role="option"]:visible')
    return [o.strip() for o in options.all_inner_texts() if o.strip()]


def read_page(page):
    """Return the questions on the current page that are still empty."""
    questions = []
    for q in page.evaluate(READ_PAGE):
        if q.pop("filled"):
            continue
        if q["kind"] == "dropdown":
            # Workday only shows a dropdown's choices once it's opened.
            button = page.locator(f'[data-ia-key="{q["key"]}"]')
            try:
                button.click()
                page.locator('[role="option"]').first.wait_for(timeout=3000)
                q["options"] = _visible_options(page)
            except Exception:
                pass
            finally:
                page.keyboard.press("Escape")
        questions.append(Question(**q))
    return questions


def _choose_option(page, text, timeout=4000):
    page.locator('[role="option"]').first.wait_for(timeout=timeout)
    exact = page.get_by_role("option", name=text, exact=True)
    (exact.first if exact.count() else page.locator('[role="option"]', has_text=text).first).click()


def fill_page(page, questions, answers, resume_pdf, log=print):
    """Fill the current page. Returns the questions left for you."""
    left = []
    pdf_name = resume_pdf.rsplit("/", 1)[-1] if resume_pdf else ""
    for q in questions:
        field = page.locator(f'[data-ia-key="{q.key}"]')
        try:
            if q.kind == "file":
                label = q.label.lower()
                already = pdf_name and page.get_by_text(pdf_name).count() > 0
                if resume_pdf and not already and ("resume" in label or "cv" in label or "upload" in label
                                                   or "select files" in label or "file" in label):
                    field.set_input_files(resume_pdf)
                    log("  ✓ uploaded tailored resume PDF")
                continue
            answer = answers.get(q.key)
            if answer is None:
                if q.required:
                    left.append(q)
                continue
            if q.kind in ("text", "textarea"):
                field.fill(answer)
            elif q.kind == "dropdown":
                field.click()
                _choose_option(page, answer)
            elif q.kind == "prompt":
                field.click()
                field.fill(answer)
                field.press("Enter")       # Workday's search boxes search on Enter
                _choose_option(page, answer, timeout=5000)
            elif q.kind == "radio":
                page.locator(f'[data-ia-key="{q.key}-{q.options.index(answer)}"]').check(force=True)
            elif q.kind == "checkbox":
                field.check(force=True)
        except Exception as e:
            log(f"  ! couldn't fill '{q.label[:50]}': {e.__class__.__name__}")
            page.keyboard.press("Escape")
            left.append(q)
    return left


def assist(page, url, claude, model, profile, resume_text, resume_pdf, log=print):
    """Walk through a Workday application with you, one page at a time."""
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    print("  Workday, page by page:")
    print("   1. In the browser: click Apply, then 'Autofill with Resume', and sign in")
    print("      (or create an account; the browser remembers it next time).")
    print("   2. On EACH page, come back here and press Enter. The agent fills that page.")
    print("   3. Check the page, then click Next/Continue in the browser yourself.")
    print("   4. On the Review page, YOU click Submit. Then type d here.")
    while True:
        choice = input("\n  [Enter] fill this page    [d] done with this job\n  > ").strip().lower()
        if choice == "d":
            return
        try:
            questions = read_page(page)
        except Exception as e:
            print(f"  ! Couldn't read this page ({e.__class__.__name__}). Fill it in yourself.")
            continue
        if not questions:
            print("  Nothing empty to fill on this page.")
            continue
        answers = plan_answers(claude, model, profile, resume_text, questions)
        left = fill_page(page, questions, answers, resume_pdf, log)
        filled = len([q for q in questions if q.key in answers])
        print(f"  ✓ filled {filled} field(s) on this page.")
        if left:
            print(f"  Left for you ({len(left)}):")
            for q in left:
                print(f"    - {q.label[:90]}")
