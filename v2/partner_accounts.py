"""Native Partner setup with in-memory throwaway passwords; no secret output."""
import secrets


def create_partner(client, origin, profile):
    """Use the Owner's authenticated HTTPS client; reset real logins later."""
    if set(profile) != {"slug", "display_name", "email"}:
        raise ValueError("Partner profile requires exactly slug, display_name and email")
    password = secrets.token_urlsafe(48)
    try:
        response = client.post(
            "/admin/api/principals",
            headers={"Origin": origin},
            json={**profile, "kind": "human", "role": "partner", "tier": 3,
                  "password": password},
        )
        # Native account creation returns status/id only to the operator.
        # Avoid raising HTTP exceptions that can retain a credential-bearing request.
        if response.status_code != 201:
            raise RuntimeError("Partner creation refused; inspect status only")
        return response.json()["principal"]["id"]
    finally:
        del password
