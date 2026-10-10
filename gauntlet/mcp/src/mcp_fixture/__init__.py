"""A one-tool MCP server: enough to prove the SDK, pydantic's compiled core and stdio work from a
bundle. (mcp 2.x: FastMCP became MCPServer.)"""

from mcp.server.mcpserver import MCPServer

server = MCPServer("bundleup-fixture")


@server.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def main() -> None:
    server.run()  # stdio, as MCP clients start servers
