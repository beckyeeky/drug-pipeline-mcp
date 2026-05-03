#!/usr/bin/env python3
"""Drug Pipeline MCP — CLI entry point.

Usage:
  drug-pipeline              # Start stdio MCP server
  drug-pipeline --http       # Start HTTP/SSE server (port 8081)
  drug-pipeline --version    # Show version
  drug-pipeline --list-tools # List available tools
"""
import sys


def main():
    args = sys.argv[1:]

    if "--version" in args:
        from drug_pipeline import __version__
        print(f"drug-pipeline v{__version__}")
        return

    if "--list-tools" in args:
        from drug_pipeline.server import TOOLS
        for name in sorted(TOOLS.keys()):
            desc = TOOLS[name]["description"][:60] + "..."
            print(f"  {name:25s} {desc}")
        return

    if "--http" in args or "--sse" in args:
        host = "0.0.0.0"
        port = 8081
        for i, a in enumerate(args):
            if a == "--host" and i + 1 < len(args):
                host = args[i + 1]
            if a == "--port" and i + 1 < len(args):
                port = int(args[i + 1])
        from drug_pipeline.server import run_http
        import asyncio
        asyncio.run(run_http(host=host, port=port))
        return

    # Default: stdio
    from drug_pipeline.server import run_stdio
    run_stdio()


if __name__ == "__main__":
    main()
