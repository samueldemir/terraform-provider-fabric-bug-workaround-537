#!/usr/bin/env python3
import argparse
import os
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


FABRIC_API = "https://api.fabric.microsoft.com/v1"
FABRIC_RESOURCE = "https://api.fabric.microsoft.com"
AZURE_AD_TOKEN_EXCHANGE_AUDIENCE = "api://AzureADTokenExchange"
OIDC_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"


def run_az(args):
    result = subprocess.run(
        ["az", *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def get_github_oidc_token():
    request_url = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL")
    request_token = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
    if not request_url or not request_token:
        return None

    separator = "&" if urllib.parse.urlparse(request_url).query else "?"
    url = (
        f"{request_url}{separator}audience="
        f"{urllib.parse.quote(AZURE_AD_TOKEN_EXCHANGE_AUDIENCE, safe='')}"
    )
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {request_token}"})
    with urllib.request.urlopen(req) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["value"]


def exchange_github_oidc_token(tenant_id, client_id, oidc_token):
    url = f"https://login.microsoftonline.com/{urllib.parse.quote(tenant_id)}/oauth2/v2.0/token"
    body = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_assertion": oidc_token,
            "client_assertion_type": OIDC_ASSERTION_TYPE,
            "grant_type": "client_credentials",
            "scope": f"{FABRIC_RESOURCE}/.default",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["access_token"]


def get_access_token(tenant_id, client_id):
    if tenant_id and client_id:
        oidc_token = get_github_oidc_token()
        if oidc_token:
            return exchange_github_oidc_token(tenant_id, client_id, oidc_token)

    return run_az(
        [
            "account",
            "get-access-token",
            "--resource",
            FABRIC_RESOURCE,
            "--query",
            "accessToken",
            "--output",
            "tsv",
        ]
    )


def request(method, url, token, body=None):
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"message": raw}
        return error.code, payload


def list_assignments(gateway_id, token):
    assignments = []
    url = f"{FABRIC_API}/gateways/{urllib.parse.quote(gateway_id)}/roleAssignments"

    while url:
        status, payload = request("GET", url, token)
        if status != 200:
            raise RuntimeError(f"Failed to list gateway role assignments: HTTP {status}: {json.dumps(payload)}")

        assignments.extend(payload.get("value", []))
        url = payload.get("continuationUri")

    return assignments


def find_assignment(assignments, principal_id):
    for assignment in assignments:
        principal = assignment.get("principal") or {}
        if principal.get("id", "").lower() == principal_id.lower():
            return assignment
    return None


def ensure_assignment(gateway_id, principal_id, principal_type, role, tenant_id, client_id):
    print(
        f"Ensuring Fabric gateway role assignment: "
        f"gateway_id={gateway_id}, principal_id={principal_id}, "
        f"principal_type={principal_type}, role={role}",
        flush=True,
    )
    token = get_access_token(tenant_id, client_id)

    assignment = find_assignment(list_assignments(gateway_id, token), principal_id)
    if assignment and assignment.get("role") == role:
        print(f"Gateway role assignment already exists for {principal_id} with role {role}.", flush=True)
        return

    if assignment:
        assignment_id = assignment["id"]
        url = (
            f"{FABRIC_API}/gateways/{urllib.parse.quote(gateway_id)}"
            f"/roleAssignments/{urllib.parse.quote(assignment_id)}"
        )
        status, payload = request("PATCH", url, token, {"role": role})
        if status not in (200, 202):
            raise RuntimeError(
                f"Failed to update gateway role assignment {assignment_id}: "
                f"HTTP {status}: {json.dumps(payload)}"
            )
        print(f"Updated gateway role assignment for {principal_id} to role {role}.", flush=True)
        return

    url = f"{FABRIC_API}/gateways/{urllib.parse.quote(gateway_id)}/roleAssignments"
    body = {
        "principal": {
            "id": principal_id,
            "type": principal_type,
        },
        "role": role,
    }
    status, payload = request("POST", url, token, body)
    if status == 201:
        print(f"Created gateway role assignment for {principal_id} with role {role}.", flush=True)
        return

    # If a previous Terraform apply created the assignment and then failed during
    # provider consistency checks, Fabric may report a duplicate here. Re-read and
    # accept the assignment if it now exists with the requested role.
    assignment = find_assignment(list_assignments(gateway_id, token), principal_id)
    if assignment and assignment.get("role") == role:
        print(f"Gateway role assignment already exists for {principal_id} with role {role}.", flush=True)
        return

    raise RuntimeError(f"Failed to create gateway role assignment: HTTP {status}: {json.dumps(payload)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway-id", required=True)
    parser.add_argument("--principal-id", required=True)
    parser.add_argument("--principal-type", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--tenant-id")
    parser.add_argument("--client-id")
    args = parser.parse_args()

    try:
        ensure_assignment(
            args.gateway_id,
            args.principal_id,
            args.principal_type,
            args.role,
            args.tenant_id,
            args.client_id,
        )
    except Exception as error:
        print(error, file=sys.stderr, flush=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
