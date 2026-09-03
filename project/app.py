import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


class _SuppressOtelDetachWarning(logging.Filter):
    def filter(self, record):
        return "Failed to detach context" not in record.getMessage()


logging.getLogger("opentelemetry.context").addFilter(_SuppressOtelDetachWarning())

import gradio as gr
import uvicorn

import config
from api.app import create_api_app
from application import ApplicationContainer
from ui.css import custom_css
from ui.gradio_app import create_gradio_ui


def create_app():
    container = ApplicationContainer()
    api = create_api_app(container)
    gui = create_gradio_ui(container)
    # Mounted Gradio apps do not get launch()'s implicit queue setup. Build the
    # queue explicitly so ChatInterface and progress-enabled callbacks have
    # active workers under the shared FastAPI lifespan.
    gui.queue(default_concurrency_limit=2)
    return gr.mount_gradio_app(api, gui, path="/", css=custom_css)


app = create_app()


if __name__ == "__main__":
    print(f"\nLaunching HKU AGENTS at {config.API_BASE_URL}")
    uvicorn.run(app, host=config.APP_HOST, port=config.APP_PORT)
