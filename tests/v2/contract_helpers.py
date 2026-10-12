"""Shared response assertions; never import helpers from another test module."""


def denied(response, code, step=None):
    assert response.status_code in (401, 403)
    body = response.json()
    assert body["code"] == code
    if response.status_code == 403:
        assert body["outcome"] == "DENY"
        assert isinstance(body["detail"], str)
        assert isinstance(body["remedy"], str)
    if step is not None:
        assert body["step"] == step
