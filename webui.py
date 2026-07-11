from dotenv import load_dotenv
load_dotenv()
import os
import argparse
import atexit
import logging

# Disable Langfuse entirely when keys are not configured.
# Must be set before any langfuse import so the library never initialises.
_langfuse_configured = bool(
    os.getenv("LANGFUSE_PUBLIC_KEY", "").strip() and
    os.getenv("LANGFUSE_SECRET_KEY", "").strip()
)
if not _langfuse_configured:
    os.environ["LANGFUSE_ENABLED"] = "false"

    # Install a filter on the ROOT logger that drops all langfuse records.
    # This survives any logger reconfiguration the langfuse library does
    # because root-level filters cannot be bypassed by child loggers.
    class _DropLangfuse(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return not record.name.startswith("langfuse")

    logging.root.addFilter(_DropLangfuse())

# Suppress OpenTelemetry noise
logging.getLogger("opentelemetry.exporter.otlp.proto.http.trace_exporter").setLevel(logging.CRITICAL)
logging.getLogger("opentelemetry").setLevel(logging.WARNING)

from src.webui.interface import theme_map, create_ui
from src.webui.webui_manager import WebuiManager


logger = logging.getLogger(__name__)


def main():
    if _langfuse_configured:
        try:
            from langfuse import get_client
            langfuse_client = get_client()
            atexit.register(langfuse_client.flush)
            logger.info("Langfuse observability initialized.")
        except Exception as exc:
            logger.warning("Could not initialize Langfuse: %s", exc)

    parser = argparse.ArgumentParser(description="AI Job Applier")
    parser.add_argument("--ip",    type=str, default="127.0.0.1", help="IP address to bind to")
    parser.add_argument("--port",  type=int, default=7788,         help="Port to listen on")
    parser.add_argument("--theme", type=str, default="Legion",
                        choices=list(theme_map.keys()),            help="UI theme")
    args = parser.parse_args()

    # Fetch Airtable jobs BEFORE building the UI so the table is pre-populated
    ui_manager = WebuiManager()
    try:
        from src.utils import airtable_client
        logger.info("Fetching unapplied jobs from Airtable at startup…")
        ui_manager.airtable_jobs = airtable_client.get_unapplied_jobs()
        ui_manager.airtable_loaded = True
        logger.info("Loaded %d unapplied job(s) from Airtable.", len(ui_manager.airtable_jobs))
    except Exception as exc:
        logger.warning("Could not load Airtable jobs at startup: %s", exc)
        ui_manager.airtable_jobs = []
        ui_manager.airtable_loaded = False

    demo, ui_manager = create_ui(theme_name=args.theme, ui_manager=ui_manager)
    demo.queue().launch(server_name=args.ip, server_port=args.port)


if __name__ == '__main__':
    main()
