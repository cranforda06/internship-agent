"""One shared way to ask Claude a question and get a structured answer back.

Used by scoring (Phase 2) and resume tailoring (Phase 3). It also keeps a
running total of tokens used so each command can print what it cost.
"""

import json

import anthropic

# Price per million tokens (input, output) in US dollars.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}


class ClaudeError(Exception):
    """Claude couldn't produce a usable answer (declined, cut off, bad format)."""


class Claude:
    def __init__(self, api_key):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.cost_so_far = 0.0
        self.input_tokens = 0
        self.output_tokens = 0
        self.priced = True  # False if a model's price is unknown

    def ask(self, model, system, prompt, schema, effort="medium", max_tokens=16000):
        """Send one request and return Claude's answer as a Python dict
        matching `schema` (a JSON schema)."""
        response = self.client.beta.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            # If Claude's safety filter wrongly declines a request, the API
            # retries it on a fallback model automatically.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        self._add_usage(model, response.usage)

        if response.stop_reason == "refusal":
            raise ClaudeError("Claude declined this request.")
        if response.stop_reason == "max_tokens":
            raise ClaudeError("The answer was cut off before it finished.")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise ClaudeError("Claude's answer had no text in it.")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ClaudeError(f"Claude's answer wasn't valid JSON: {e}")

    def _add_usage(self, model, usage):
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        if model in PRICES:
            price_in, price_out = PRICES[model]
            self.cost_so_far += (usage.input_tokens * price_in + usage.output_tokens * price_out) / 1_000_000
        else:
            self.priced = False

    def cost_line(self):
        if not self.input_tokens:
            return "No API calls made."
        cost = f"${self.cost_so_far:.3f}" if self.priced else "unknown (model price not listed)"
        return (f"Cost of this run: {cost} "
                f"({self.input_tokens:,} input + {self.output_tokens:,} output tokens)")
