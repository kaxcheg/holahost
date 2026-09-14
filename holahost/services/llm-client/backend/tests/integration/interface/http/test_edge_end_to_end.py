"""The real application, against a real Postgres and a real JWKS endpoint.

Nothing here is faked: the app under test is the one `scripts/bootstrap.py` builds for
uvicorn, with the middleware stack `create_edge_app` assembled and tokens signed by a key
the service fetches over HTTP. What it proves is that the composition root, the platform
edge and the database line up — the failures that unit tests with overridden dependencies
cannot see.

The service's own routes are tested beside this file, using the same `client` and
`auth_headers` fixtures.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from interface.http.api_base import API_BASE_URL

pytestmark = pytest.mark.integration

_HEALTH_URL = f"{API_BASE_URL}/health"
# Deliberately not a route: authentication runs before routing, so an unknown path under
# the base URL is answered by the edge, which is what these tests are about.
_GUARDED_URL = f"{API_BASE_URL}/no-such-route"


class TestHealth:
    def test_it_reports_ok_against_a_real_database(self, client: TestClient) -> None:
        response = client.get(_HEALTH_URL)

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_it_needs_neither_a_token_nor_a_request_id(self, client: TestClient) -> None:
        # The one public path: `public_paths` exempts it from authentication, and the same
        # declaration is what exempts it from the `X-Request-ID` requirement.
        response = client.get(_HEALTH_URL)

        assert response.status_code == 200


class TestTheEdgeRefusesBeforeRouting:
    def test_a_missing_request_id_is_answered_first(self, client: TestClient) -> None:
        # Outermost middleware, so this answers even though the request also carries no
        # token — the order is what makes every later refusal carry a correlation id.
        response = client.get(_GUARDED_URL)

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "MalformedRequestError"

    def test_a_missing_token_is_answered_401(self, client: TestClient) -> None:
        response = client.get(_GUARDED_URL, headers={"X-Request-ID": "e2e-no-token"})

        assert response.status_code == 401
        assert response.headers["X-Request-ID"] == "e2e-no-token"

    def test_a_valid_token_reaches_routing(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        # 404 from Starlette's router, not 401: getting this far means the JWKS fetch, the
        # signature check and every claim assertion passed against a real key.
        response = client.get(_GUARDED_URL, headers=auth_headers)

        assert response.status_code == 404
