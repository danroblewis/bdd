from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class Task:
    id: int
    title: str
    status: str = "todo"
    priority: int = 1
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        return cls(**data)
