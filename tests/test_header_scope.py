"""The X-Skill-Pack header, exercised over real HTTP.

The header only exists inside an HTTP request, so an in-memory client cannot
reach this code path at all. These tests run the ASGI app on a real port.
"""

import asyncio
import socket
import threading

import pytest
import uvicorn
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from kubed.skills_mcp.server import build_server


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server_url(skills_dir_module):
    """Serve the skills app on a loopback port for the duration of the module."""
    port = _free_port()
    app = build_server(skills_dir_module).http_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        threading.Event().wait(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)


async def call(url, tool, headers=None, **args):
    transport = StreamableHttpTransport(url, headers=headers or {})
    async with Client(transport) as client:
        return (await client.call_tool(tool, args)).content[0].text


@pytest.mark.integration
async def test_no_header_sees_every_pack(server_url):
    out = await call(server_url, "list_packs")
    assert "flatsource" in out and "deepsource" in out


@pytest.mark.integration
async def test_header_hides_the_other_pack(server_url):
    out = await call(server_url, "list_packs", headers={"X-Skill-Pack": "flatsource"})
    assert "flatsource" in out
    assert "deepsource" not in out


@pytest.mark.integration
async def test_header_beats_a_wider_pack_argument(server_url):
    """The model asking for the other pack must not widen past the header."""
    out = await call(
        server_url,
        "list_skills",
        headers={"X-Skill-Pack": "flatsource"},
        pack="deepsource",
    )
    assert "gamma" not in out and "delta" not in out


@pytest.mark.integration
async def test_header_blocks_reading_outside_the_pack(server_url):
    """Knowing a skill's name is not enough to read it from another pack."""
    out = await call(
        server_url, "read_skill", headers={"X-Skill-Pack": "flatsource"}, skill="gamma"
    )
    assert out.startswith("Unknown skill")


@pytest.mark.integration
async def test_header_still_allows_its_own_pack(server_url):
    out = await call(
        server_url, "read_skill", headers={"X-Skill-Pack": "flatsource"}, skill="alpha"
    )
    assert "First skill." in out


@pytest.mark.integration
async def test_error_message_does_not_leak_other_packs(server_url):
    """A pinned client must not learn the other packs' names from an error."""
    out = await call(
        server_url, "list_skills", headers={"X-Skill-Pack": "flatsource"}, pack="nope"
    )
    assert "flatsource" in out
    assert "deepsource" not in out and "plugin-a" not in out
