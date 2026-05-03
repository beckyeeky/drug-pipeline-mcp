#!/usr/bin/env python3
"""HTTP/SSE Wrapper for drug-pipeline-mcp — start with --port 8081"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, "/home/j/drug-pipeline")

# Re-use the drug-pipeline app (import side-effect registers tools)
from drug_pipeline.server import app  # mcp.Server instance

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()

    # Use MCP's built-in SSE transport with uvicorn
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route
    import uvicorn

    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await app.run(
                streams[0], streams[1], app.create_initialization_options()
            )

    starlette_app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )

    print(f"💊 drug-pipeline MCP Server (SSE) on port {args.port}")
    print(f"   SSE: http://0.0.0.0:{args.port}/sse")
    uvicorn.run(starlette_app, host="0.0.0.0", port=args.port)
