"""Exercise every service against the checked-in contract's synthetic examples."""

import inspect
import json
import re
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import httpx2
import pytest
import yaml

from opendart import OpenDart

REFERENCE = Path(__file__).resolve().parents[3] / "api_reference"


def contract_cases():
    """Build one parametrized test case per supported service from local examples.

    Yields:
        pytest.ParameterSet: Resource group, method, route, parameters, and synthetic response body.
    """
    for source in sorted((REFERENCE / "paths").glob("*.yaml")):
        for route, item in yaml.safe_load(source.read_text()).items():
            operation = item["get"]
            content = operation["responses"]["200"]["content"]
            if not route.endswith(".json") and "application/zip" not in content:
                continue
            stem = route.split(".")[0][1:]
            name = {"list": "search", "corpCode": "corporation_codes"}.get(
                stem,
                re.sub(r"([A-Z])", r"_\1", stem).lower(),
            )
            params = {}
            for parameter in operation.get("parameters", []):
                filename, fragment = parameter["$ref"].split("#/")
                definition = yaml.safe_load((source.parent / filename).read_text())[fragment]
                params[definition["name"]] = definition["example"]
            if "application/json" in content:
                body = content["application/json"]["examples"]["success"]["value"]
            else:
                archive = BytesIO()
                with ZipFile(archive, "w") as zipped:
                    zipped.writestr("sample.xml", "<synthetic/>")
                body = archive.getvalue()
            yield pytest.param(source.stem.replace("-", "_"), name, route, params, body, id=route)


CASES = list(contract_cases())


def handler_for(settings, route, params, body):
    """Create a mock handler that verifies route, authentication, and query encoding.

    Args:
        settings (OpenDartSettings): Validated fixture settings with a synthetic API key.
        route (str): Expected endpoint path without the /engapi prefix.
        params (dict[str, str | int | list[str]]): Synthetic query parameters from the
            contract examples.
        body (dict | bytes): Expected successful JSON payload or ZIP archive bytes.

    Returns:
        Callable[[httpx2.Request], httpx2.Response]: Handler serving the supplied successful response.
    """

    def handle(request):
        """Verify an outgoing contract request and return its synthetic response.

        Args:
            request (httpx2.Request): Outgoing SDK request to inspect.

        Returns:
            httpx2.Response: Successful JSON or archive response.

        Raises:
            AssertionError: The route, headers, method, authentication, or query values differ
                from the contract.
        """
        assert request.method == "GET"
        assert request.url.host == "engopendart.fss.or.kr"
        assert request.url.path == "/engapi" + route
        expected = {
            key: ",".join(value) if isinstance(value, list) else str(value)
            for key, value in params.items()
        }
        expected["crtfc_key"] = settings.api_key.get_secret_value()
        assert dict(request.url.params) == expected
        assert request.headers["accept-encoding"] == "identity"
        if isinstance(body, bytes):
            return httpx2.Response(200, content=body)
        return httpx2.Response(200, json=body)

    return handle


def check_result(result, body):
    """Compare a parsed SDK result with the original synthetic response body.

    Args:
        result (ResponseModel | bytes): Returned SDK response.
        body (dict | bytes): Original successful mock response payload.

    Raises:
        AssertionError: The response differs from the expected bytes or aliased model
            fields.
    """
    if isinstance(body, bytes):
        assert result == body
    else:
        assert result.model_dump(exclude_unset=True, by_alias=True) == body


def test_service_count():
    """Verify that every catalog service has exactly one SDK contract case."""
    assert len(CASES) == 85
    catalog = json.loads((REFERENCE / "sources/catalog.json").read_text())
    assert len(CASES) == sum(len(group["services"]) for group in catalog["groups"])


@pytest.mark.anyio
@pytest.mark.parametrize("group,name,route,params,body", CASES)
async def test_contract(settings, group, name, route, params, body):
    """Verify each asynchronous endpoint against its synthetic contract example.

    Args:
        settings (OpenDartSettings): Validated fixture settings with a synthetic API key.
        group (str): Resource attribute for the service category.
        name (str): Generated resource method name.
        route (str): Expected endpoint path without the /engapi prefix.
        params (dict[str, str | int | list[str]]): Synthetic query parameters from the
            contract examples.
        body (dict | bytes): Expected successful JSON payload or ZIP archive bytes.
    """
    transport = httpx2.MockTransport(handler_for(settings, route, params, body))
    async with OpenDart(settings, transport=transport) as client:
        method = getattr(getattr(client, group), name)
        assert inspect.iscoroutinefunction(method)
        check_result(await method(**params), body)
    assert client.is_closed
