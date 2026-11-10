"""The Job record that every source (Simplify, Greenhouse, Lever) produces.

Each source looks different, so each one converts its data into this same
shape. That way the rest of the agent only has to understand one format.
"""

from dataclasses import dataclass


@dataclass
class Job:
    company: str
    title: str
    url: str
    location: str        # e.g. "Richmond, VA; Remote in USA"
    source: str          # "simplify", "greenhouse" or "lever"
    description: str = ""  # full job description as plain text ("" if unknown)
    posted: str = ""       # date posted, like "2026-11-01" ("" if unknown)
