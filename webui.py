from dotenv import load_dotenv
load_dotenv()
import argparse
import atexit
import logging
from src.webui.interface import theme_map, create_ui

logger = logging.getLogger(__name__)


def main():
    try:
        from langfuse import get_client
        langfuse_client = get_client()
        atexit.register(langfuse_client.flush)
        logger.info("Langfuse observability initialized.")
    except Exception as exc:
        logger.warning("Could not initialize Langfuse at startup: %s", exc)

    parser = argparse.ArgumentParser(description="Gradio WebUI for Browser Agent")
    parser.add_argument("--ip", type=str, default="127.0.0.1", help="IP address to bind to")
    parser.add_argument("--port", type=int, default=7788, help="Port to listen on")
    parser.add_argument("--theme", type=str, default="Ocean", choices=theme_map.keys(), help="Theme to use for the UI")
    args = parser.parse_args()

    demo, ui_manager = create_ui(theme_name=args.theme)

    # --- Prefetch Airtable jobs into memory at startup ---
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

    demo.queue().launch(server_name=args.ip, server_port=args.port)


if __name__ == '__main__':
    main()
