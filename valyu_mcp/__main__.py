"""Entry point to run the Valyu MCP HTTP server."""

import logging
import os

from valyu_mcp.server import mcp


def main() -> None:
    """Run the FastMCP HTTP server."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    host = os.getenv("FASTMCP_HOST", "0.0.0.0")
    port = int(os.getenv("FASTMCP_PORT", "8012"))
    mcp.run(transport="http", host=host, port=port)


if __name__ == "__main__":
    main()
