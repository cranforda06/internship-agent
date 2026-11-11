"""Assisted filling for Workday applications (never submits, never clicks Next).

Workday applications need a separate account at each company, and they're
spread over several pages. So this works side by side with you:

  1. You click Apply, choose "Autofill with Resume", and sign in or create
     the account yourself.
  2. Each page fills itself a moment after it loads: the agent reads that
     page's questions, uploads your tailored resume if the page asks for it,
     and fills in what it can from your profile.
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
  // A radio button's choice text ("Yes"/"No"). Workday doesn't always link the
  // label the standard way, so try several places it can be.
  const radioText = el => {
    const t = ownLabel(el);
    if (t) return t;
    const wrap = el.closest('label');
    if (wrap && textOf(wrap)) return textOf(wrap);
    const sib = el.nextElementSibling;
    if (sib && textOf(sib)) return textOf(sib);
    const parent = el.parentElement;
    if (parent && textOf(parent) && textOf(parent).length < 60) return textOf(parent);
    return clean(el.value);
  };
  // Radios belong to the same question if they're in the same form field box,
  // even when Workday gives each button a different name.
  let groupCounter = 0;
  const radioGroupId = el => {
    const box = el.closest('[data-automation-id^="formField"], fieldset, [role="radiogroup"]');
    if (box) {
      if (!box.dataset.iaGroup) box.dataset.iaGroup = 'g' + groupCounter++;
      return box.dataset.iaGroup;
    }
    return el.name || 'loose';
  };

  document.querySelectorAll('[data-ia-key]').forEach(e => e.removeAttribute('data-ia-key'));
  document.querySelectorAll('[data-ia-group]').forEach(e => e.removeAttribute('data-ia-group'));
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
      const group = radioGroupId(el);
      if (!radioGroups[group]) {
        const key = 'k' + n++;
        const label = fieldLabel(el) || textOf(el.closest('[role="radiogroup"]')?.previousElementSibling);
        radioGroups[group] = {key, label, kind: 'radio', options: [], required: isRequired(el, label),
                              filled: false};
        out.push(radioGroups[group]);
      }
      const g = radioGroups[group];
      el.setAttribute('data-ia-key', g.key + '-' + g.options.length);
      g.options.push(radioText(el));
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


def read_page(page, skip=()):
    """Return the questions on the current page that are still empty.

    Questions in `skip` (as (kind, label)) are left out, and their dropdowns
    are NOT clicked open, so already-handled fields aren't touched again.
    """
    questions = []
    for q in page.evaluate(READ_PAGE):
        if q.pop("filled") or (q["kind"], q["label"]) in skip:
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
                wanted = (any(w in label for w in ("resume", "cv", "upload", "file", "attach", "drop"))
                          and not any(w in label for w in ("cover", "transcript", "portfolio")))
                if resume_pdf and not already and wanted:
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
                radio = page.locator(f'[data-ia-key="{q.key}-{q.options.index(answer)}"]')
                radio.check(force=True)
                if not radio.is_checked():           # Workday sometimes ignores that; click it directly
                    radio.evaluate("el => el.click()")
            elif q.kind == "checkbox":
                field.check(force=True)
        except Exception as e:
            log(f"  ! couldn't fill '{q.label[:50]}': {e.__class__.__name__}")
            page.keyboard.press("Escape")
            left.append(q)
    return left


# A short description of "which page is this": the step name Workday shows,
# plus the labels of the visible fields. When it changes, a new page loaded.
PAGE_SIGNATURE = r"""() => {
  const clean = t => (t || '').replace(/\s+/g, ' ').trim();
  const step = document.querySelector('[data-automation-id="progressBarActiveStep"], h2');
  // Only the questions' own labels, not error messages or dropdown contents,
  // so the agent's own clicking doesn't look like a new page.
  const labels = [...document.querySelectorAll(
      '[data-automation-id^="formField"] > label, [data-automation-id^="formField"] legend, fieldset > legend, label[for]')]
    .filter(l => (l.offsetWidth || l.offsetHeight) && !l.closest('[role="listbox"]'))
    .map(l => clean(l.innerText).replace(/\*/g, '')).filter(Boolean);
  return {
    step: step ? clean(step.innerText) : '',
    labels: [...new Set(labels)].sort(),
    password: !!document.querySelector('input[type=password]'),
    menuOpen: !!document.querySelector('[role="listbox"] [role="option"]'),
    // Upload boxes count too: the "Autofill with Resume" page has nothing else.
    files: document.querySelectorAll('input[type=file]').length,
  };
}"""


# Most automatic fills per page (a page that keeps changing is left to you).
MAX_AUTO_ROUNDS = 3


def _fill_new_fields(page, attempted, claude, model, profile, resume_text, resume_pdf, log):
    """Fill fields on the current page that haven't been tried yet.

    `attempted` holds the labels already handled on this page, so a field
    you changed is never overwritten, and only newly revealed fields get filled.
    """
    questions = read_page(page, skip=attempted)
    if not questions:
        return
    attempted.update((q.kind, q.label) for q in questions)
    answers = plan_answers(claude, model, profile, resume_text, questions)
    left = fill_page(page, questions, answers, resume_pdf, log)
    filled = len([q for q in questions if q.key in answers])
    log(f"  ✓ filled {filled} field(s) on this page.")
    if left:
        log(f"  Left for you ({len(left)}):")
        for q in left:
            log(f"    - {q.label[:90]}")
    log("  Check the page, then click Next in the browser.")


def _print_keyboard_help():
    print("  Workday, hands-free:")
    print("   1. In the browser: click Apply, then 'Autofill with Resume', and sign in")
    print("      (or create an account; the browser remembers it next time).")
    print("   2. Each application page fills itself a moment after it loads.")
    print("      Check it, then click Next/Continue yourself.")
    print("   3. On the Review page, YOU click Submit. Then type d here.")
    print("  Here: [d] done with this job   [v] view resume   [u] upload resume again   "
          "[Enter] re-fill this page")


def assist(page, url, claude, model, profile, resume_text, resume_pdf, log=print, poll_seconds=1.0,
           typed=None, time_limit=None):
    """Walk through a Workday application with you, filling each page as it loads.

    `typed` is where your keys come from: your keyboard if None, or a queue
    the home page's buttons put keys into. `time_limit` is only for tests.
    """
    import queue
    import threading
    import time

    from agent.apply.runner import show_resume

    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    # Your typing is read in the background, so the agent can keep watching
    # the browser at the same time.
    if typed is None:
        _print_keyboard_help()
        typed = queue.Queue()

        def read_keyboard():
            while True:
                try:
                    typed.put(input().strip().lower())
                except EOFError:
                    typed.put("d")
                    return

        threading.Thread(target=read_keyboard, daemon=True).start()

    current_page, attempted, last_seen, stable_since, rounds = None, set(), None, 0.0, 0
    last_filled = None   # the page state we last filled, so we don't keep re-checking it
    started = time.time()
    while time_limit is None or time.time() - started < time_limit:
        try:
            choice = typed.get_nowait()
        except queue.Empty:
            choice = None
        if choice == "d":
            return
        if choice == "v":
            show_resume(resume_pdf)
        elif choice == "u":
            # Re-upload the tailored resume to every upload box on this page.
            boxes = page.locator('input[type="file"]')
            if boxes.count() and resume_pdf:
                for i in range(boxes.count()):
                    boxes.nth(i).set_input_files(resume_pdf)
                log("  ✓ uploaded your tailored resume again.")
            else:
                log("  No upload box on this page.")
        elif choice == "":
            attempted = set()   # Enter: try every empty field on this page again
            last_filled = None
            rounds = 0

        try:
            sig = page.evaluate(PAGE_SIGNATURE)
        except Exception:
            time.sleep(poll_seconds)   # page is mid-navigation
            continue

        # Only fill real application pages: never sign-in pages, never the
        # job posting itself, and only once the page has stopped changing.
        on_application = ("/apply" in page.url and not sig["password"]
                          and (sig["labels"] or sig["files"])
                          and not sig["menuOpen"])   # a dropdown is open: you're busy, wait
        fingerprint = (page.url, sig["step"], tuple(sig["labels"]), sig["files"])
        if fingerprint != last_seen:
            last_seen, stable_since = fingerprint, time.time()
        settled = time.time() - stable_since >= 1.5

        # Fill only when the page changed since we last filled it (a new page,
        # or new fields appeared), so we're not clicking around while you work.
        if on_application and settled and fingerprint != last_filled:
            this_page = (page.url, sig["step"])
            if this_page != current_page:
                current_page, attempted, rounds = this_page, set(), 0
            rounds += 1
            if rounds > MAX_AUTO_ROUNDS:
                if rounds == MAX_AUTO_ROUNDS + 1:
                    print("  (Stopped auto-filling this page so it doesn't keep changing."
                          " Press Enter here to fill it again.)")
                last_filled = last_seen = fingerprint
                time.sleep(poll_seconds)
                continue
            try:
                _fill_new_fields(page, attempted, claude, model, profile, resume_text, resume_pdf, log)
            except Exception as e:
                print(f"  ! Couldn't fill this page ({e.__class__.__name__}). Fill it in yourself.")
            try:   # remember the page as it looks AFTER filling
                after = page.evaluate(PAGE_SIGNATURE)
                last_filled = (page.url, after["step"], tuple(after["labels"]), after["files"])
            except Exception:
                last_filled = fingerprint
            last_seen = last_filled
        time.sleep(poll_seconds)
