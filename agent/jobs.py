from dataclasses import dataclass


@dataclass
class Job:
    company: str
    title: str
    url: str
    location: str
    source: str
    description: str = ""
    posted: str = ""
