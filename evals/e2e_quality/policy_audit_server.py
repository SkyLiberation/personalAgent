"""Two genuine production applications in one process for AUD-001."""

from contextlib import asynccontextmanager
import os
from pathlib import Path
import sys
from threading import Thread

from fastapi import FastAPI
import uvicorn

from personal_agent.adapters.web.api import app as primary, create_app

primary_url = os.environ["PERSONAL_AGENT_POSTGRES_URL"]
primary_data = os.environ["PERSONAL_AGENT_DATA_DIR"]
try:
    os.environ["PERSONAL_AGENT_POSTGRES_URL"] = os.environ[
        "AUDIT_E2E_SECONDARY_POSTGRES_URL"
    ]
    os.environ["PERSONAL_AGENT_DATA_DIR"] = str(
        Path(primary_data).with_name("secondary-data")
    )
    secondary = create_app()
finally:
    os.environ["PERSONAL_AGENT_POSTGRES_URL"] = primary_url
    os.environ["PERSONAL_AGENT_DATA_DIR"] = primary_data


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with primary.router.lifespan_context(primary):
        async with secondary.router.lifespan_context(secondary):
            yield


app = FastAPI(lifespan=lifespan)
app.mount("/primary", primary)
app.mount("/secondary", secondary)


if __name__ == "__main__":
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=int(sys.argv[1]))
    )

    def stop_from_parent() -> None:
        if sys.stdin.readline().strip() == "stop":
            server.should_exit = True

    Thread(target=stop_from_parent, daemon=True).start()
    server.run()
