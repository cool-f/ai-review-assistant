from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BudgetState:
    used: int
    limit: int

    @property
    def allows_ai_call(self) -> bool:
        return self.limit <= 0 or self.used < self.limit

    @property
    def percentage(self) -> float:
        return round(self.used / self.limit * 100, 1) if self.limit > 0 else 0.0
