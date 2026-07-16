import asyncio
from collections.abc import AsyncIterator
from typing import TypeVar


T = TypeVar("T")


async def drain_until_sentinel(queue) -> AsyncIterator[T]:
    """Yield queued events until the single batch-completion sentinel arrives."""
    while True:
        event = await queue.get()
        if event is None:
            return
        yield event


async def cancel_and_wait(tasks: list[asyncio.Task]) -> None:
    """Cancel unfinished solvers and wait until no task can still commit."""
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def interrupted_homework_status(total: int, answered: int) -> str:
    if total > 0 and answered >= total:
        return "completed"
    if answered > 0:
        return "partial"
    return "failed"
