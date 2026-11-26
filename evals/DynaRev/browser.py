"""Expose only the selected DynaRev task's browser actions to both agents."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from pathlib import Path
import socket
from threading import Thread
from time import monotonic, sleep
from types import SimpleNamespace
from typing import Literal, TYPE_CHECKING
from urllib.parse import SplitResult, urlsplit
from uuid import uuid4

import anyio
from browsergym.utils.obs import flatten_axtree_to_str
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import Response
import uvicorn

from src.agent_lib.env_manager import EnvironmentManager
from src.agent_lib.milestones import milestone_should_fire

if TYPE_CHECKING:
    from openai import OpenAI
    from src.models import Revision, TaskInstance

TOOL_DESCRIPTION = (
    "Browse the current task website. Use observe to read the page, click with a visible element ID, "
    "fill with an element ID and text, press with an element ID and key, scroll with x/y pixel offsets, "
    "or goto with a URL on the task website. Use the resulting page to continue the task."
)
BrowserOperation = Literal["observe", "goto", "click", "fill", "press", "scroll"]


def write_json(path: Path, content: object) -> None:
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class BrowserEpisode:
    def __init__(self, task: TaskInstance, directory: Path, judge: OpenAI, model: str):
        self.task = task
        self.directory = directory
        self.judge = judge
        self.model = model
        self.manager = EnvironmentManager(task, SimpleNamespace(headless=True))
        self.steps = 0
        self.delivered: list[str] = []
        self.attempts: list[dict] = []
        self.send: Callable[[Revision], dict]
        self.error: str | None = None
        self.completion_endpoint: str | None = None
        host = urlsplit(task.runtime["start_url"]).hostname
        if host is None:
            raise ValueError("The task start URL needs a hostname.")
        self.site_host = host.removeprefix("www.")

    def start(self) -> None:
        self.env, self.observation = self.manager.start()
        observation = self.snapshot()
        browser = self.env.page.context.browser
        write_json(self.directory / "initial-browser.json", {**observation, "browser_version": browser.version})
        if not observation["axtree"].strip() or self.page_is_blocked(observation["axtree"]):
            raise RuntimeError(f"Task website is blocked or empty at {observation['url']}")
        self.env.page.context.route("**/*", self.route)

    def allows_url(self, url: SplitResult) -> bool:
        host = url.hostname or ""
        return (url.scheme == "https" and url.username is None and url.password is None
                and (host == self.site_host or host.endswith(f".{self.site_host}")))

    def route(self, route) -> None:
        request = route.request
        if self.allows_url(urlsplit(request.url)) and request.method in {"GET", "HEAD", "POST"}:
            route.continue_()
        else:
            route.abort()

    @staticmethod
    def page_is_blocked(axtree: str) -> bool:
        text = axtree.casefold()
        return any(marker in text[:700] for marker in ("access denied", "403 forbidden", "err_", "verify you are human"))

    def snapshot(self) -> dict[str, str]:
        return {
            "url": self.observation["url"],
            "axtree": flatten_axtree_to_str(self.observation["axtree_object"]),
            "last_action_error": self.observation.get("last_action_error", ""),
        }

    def action(self, operation: BrowserOperation, target: str, value: str, x: int, y: int) -> str:
        if operation == "observe":
            return "noop()"
        if operation == "goto" and not self.allows_url(urlsplit(target)):
            raise ValueError("Navigate to a public URL on the task website.")
        args = (x, y) if operation == "scroll" else (target, value) if operation in {"fill", "press"} else (target,)
        return f"{operation}({', '.join(repr(arg) for arg in args)})"

    def perform(self, operation: BrowserOperation, target: str, value: str, x: int, y: int) -> dict[str, str]:
        if self.steps >= self.task.runtime["max_steps"]:
            raise ValueError("The browser step budget has been exhausted.")
        action = self.action(operation, target, value, x, y)
        before = self.snapshot()
        self.steps += 1
        try:
            self.observation, _, _, _, _ = self.env.step(action)
        except Exception as error:
            self.error = f"{type(error).__name__}: {error}"
            raise
        after = self.snapshot()
        if self.page_is_blocked(after["axtree"]):
            self.error = f"Browser access blocked at {after['url']}"
        self.record(action, before, [])
        if self.error is None:
            self.check_milestone(after["axtree"])
        return {**after, "axtree": after["axtree"][:20_000]}

    def check_milestone(self, axtree: str) -> None:
        if not self.revision_pending():
            return
        milestone = self.task.milestones[len(self.attempts)]
        fired, detail = milestone_should_fire(milestone, axtree, self.steps + 1, {}, self.judge, self.model)
        with (self.directory / "milestones.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"step": self.steps, "id": milestone.milestone_id, "fired": fired, **detail}) + "\n")
        if fired:
            self.deliver_revision("milestone")

    def revision_pending(self) -> bool:
        return len(self.attempts) < len(self.task.revisions) and all(item["accepted"] for item in self.attempts)

    def on_completion_candidate(self) -> None:
        if self.error or not self.revision_pending() or self.steps >= self.task.runtime["max_steps"]:
            return
        self.steps += 1
        self.record("premature_done()", self.snapshot(), [])
        self.deliver_revision("premature_done")

    def deliver_revision(self, trigger: str) -> None:
        revision = self.task.revisions[len(self.attempts)]
        result = self.send(revision)
        self.attempts.append({
            "revision": revision.revision_id, "trigger": trigger, "after_browser_step": self.steps, **result,
        })
        if result["accepted"]:
            self.delivered.append(revision.revision_id)

    def record(self, action: str, observation: dict[str, str], injected: list[str]) -> None:
        path = self.directory / f"step_{self.steps:03d}.axtree"
        path.write_text(observation["axtree"], encoding="utf-8")
        event = {"step": self.steps, "url": observation["url"], "action": action,
                 "injected_revision_ids": injected, "axtree_path": path.name}
        with (self.directory / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    def finish(self, answer: str, completed: bool) -> None:
        self.steps += 1
        action = f"send_msg_to_user({('done: ' + answer)!r})" if completed else "noop()"
        self.record(action, self.snapshot(), [])
        path = self.directory / "events.jsonl"
        events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        for item in self.attempts:
            if item["accepted"]:
                events[item["after_browser_step"]]["injected_revision_ids"].append(item["revision"])
        path.write_text("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events), encoding="utf-8")
        write_json(self.directory / "summary.json", {
            "fired_revisions": self.delivered, "steps": self.steps, "completed": completed,
            "steering": self.attempts, "browser_error": self.error,
        })


@contextmanager
def serve(episode: BrowserEpisode, *, completion_fallback: bool = False) -> Iterator[str]:
    mcp = FastMCP("dynarev", stateless_http=True, json_response=True)
    with ThreadPoolExecutor(max_workers=1) as browser:
        try:
            browser.submit(episode.start).result()

            @mcp.tool(description=TOOL_DESCRIPTION)
            async def browse(operation: BrowserOperation, target: str = "", value: str = "",
                             x: int = 0, y: int = 0) -> dict[str, str]:
                future = browser.submit(episode.perform, operation, target, value, x, y)
                return await anyio.to_thread.run_sync(future.result)

            if completion_fallback:
                completion_path = f"/turn-stopping/{uuid4().hex}"

                @mcp.custom_route(completion_path, methods=["POST"])
                async def turn_stopping(_request: Request) -> Response:
                    future = browser.submit(episode.on_completion_candidate)
                    await anyio.to_thread.run_sync(future.result)
                    return Response(status_code=204)

            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
                server = uvicorn.Server(uvicorn.Config(mcp.streamable_http_app(), log_level="warning"))
                thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
                thread.start()
                try:
                    deadline = monotonic() + 10
                    while thread.is_alive() and not server.started and monotonic() < deadline:
                        sleep(0.05)
                    if not server.started:
                        raise RuntimeError("Browser MCP HTTP startup failed")
                    base = f"http://127.0.0.1:{port}"
                    if completion_fallback:
                        episode.completion_endpoint = base + completion_path
                    yield base + "/mcp"
                finally:
                    server.should_exit = True
                    thread.join()
        finally:
            browser.submit(episode.manager.close).result()
