# OpenDART MCP

Minimal stdio server using the [official MCP Python SDK](https://py.sdk.modelcontextprotocol.io/run/).
It starts and handles MCP connections, but has no tools, resources, or prompts yet.
OpenDART tools will use the async `OpenDart` client from `opendart-sdk`.

From the repository root, run locally:

```sh
uv sync --locked --all-packages
uv run --no-sync opendart-mcp
```

`uv run --no-sync python -m opendart_mcp` is equivalent.

## Docker

From the repository root, build the image, then start it with stdin attached for
an MCP client:

```sh
docker compose -f packages/mcp/docker-compose.yml build mcp
docker compose -f packages/mcp/docker-compose.yml run --rm --no-deps -T mcp
```

Compose forwards `OPENDART_API__API_KEY` from your shell. To load the root `.env`
file explicitly, use [Compose's `--env-file` option](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/):

```sh
docker compose --env-file .env -f packages/mcp/docker-compose.yml run --rm --no-deps -T mcp
```

The empty scaffold does not require a key; add one when implementing OpenDART tools.
The build context excludes `.env`, local virtual environments, and other files
outside the package sources and workspace manifests.

To connect an MCP host, configure it to launch `docker` with these arguments
(replace `/absolute/path/to/opendart` with your checkout):

```json
{
  "mcpServers": {
    "opendart": {
      "command": "docker",
      "args": [
        "compose", "-f", "/absolute/path/to/opendart/packages/mcp/docker-compose.yml",
        "run", "--rm", "--no-deps", "-T", "mcp"
      ]
    }
  }
}
```

To load the root `.env` file for this host configuration, add `"--env-file",`
`"/absolute/path/to/opendart/.env"` before `"run"` in the arguments above.

The server uses stdio, so no ports are published. Run it through an MCP host;
when launched manually, it waits for protocol messages on stdin.
