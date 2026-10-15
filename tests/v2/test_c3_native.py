"""C3 lifecycle against the real native API in the isolated test database only."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "v2"))
from c3_common import OperatorError
from c3_mint import mint


def test_c3_real_native_refusal_and_standard_template_rotation(identity, capsys, caplog):
    case = identity

    class NativeClient:
        def request(self, method, path, **kwargs):
            return case.request(case.owner_client, method, path, **kwargs)

    subject = {**case.owner, "status": "active"}
    client = NativeClient()
    # Fixture Owner already has an active personal credential.
    with pytest.raises(OperatorError):
        mint(client, subject, "personal-ai-client")
    made = mint(client, subject, "personal-ai-client", rotate=True)
    try:
        assert made["token"].startswith("cmh_pk_")
        assert "memory.read" in made["scopes"]
        assert "principals.admin" not in made["scopes"]
        credentials = case.request(case.owner_client, "GET", "/admin/api/credentials").json()[
            "credentials"]
        personal = [row for row in credentials if row["principal_id"] == str(case.owner["id"])
                    and row["kind"] != "legacy_shared" and not row["revoked_at"]]
        assert [row["id"] for row in personal] == [str(made["id"])]
        output = capsys.readouterr()
        assert made["token"] not in output.out + output.err + caplog.text
    finally:
        assert case.request(case.owner_client, "POST",
                            f"/admin/api/credentials/{made['id']}/revoke").status_code == 200


def test_c3_agent_rotation_uses_real_contributor_bundle(identity, capsys, caplog):
    from cmh.policy.scopes import expand

    class NativeClient:
        def request(self, method, path, **kwargs):
            return identity.request(identity.owner_client, method, path, **kwargs)

    subject = {**identity.agent_a["principal"], "status": "active"}
    made = mint(NativeClient(), subject, "openclaw-agent-standard", rotate=True)
    try:
        assert made["token"].startswith("cmh_ak_")
        assert set(made["scopes"]) == set(expand(["bundle:contributor"]))
        output = capsys.readouterr()
        assert made["token"] not in output.out + output.err + caplog.text
    finally:
        assert identity.request(identity.owner_client, "POST",
                                f"/admin/api/credentials/{made['id']}/revoke").status_code == 200
