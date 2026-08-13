# Terraform Fabric gateway role assignment workaround

This repository contains a workaround for
[`microsoft/terraform-provider-fabric` issue #537](https://github.com/microsoft/terraform-provider-fabric/issues/537),
where Fabric gateway role assignments for service principals can be read back
with an inconsistent `principal.type` value.

The affected provider resource may create the role assignment successfully, then
fail the Terraform apply because the provider reads the service principal back
as either `User` or `ServicePrincipal`. Since that consistency check happens
before `lifecycle.ignore_changes` can help, this workaround avoids the broken
provider resource for service-principal gateway role assignments.

## What this does

`power-bi-rbac.tf` uses a `terraform_data` resource with `local-exec`
provisioners to call the Fabric REST API directly:

- On create/update, it ensures a Fabric gateway role assignment exists for each
  configured service principal.
- If the assignment already exists with the requested role, it exits cleanly.
- If the assignment exists with a different role, it patches the role.
- On destroy, it deletes the matching gateway role assignment.

The implementation is intentionally idempotent so repeated `terraform apply`
runs are safe.

## Files

| File | Purpose |
| --- | --- |
| `power-bi-rbac.tf` | Terraform workaround using `terraform_data` and `local-exec`. |
| `scripts/ensure_fabric_gateway_role_assignment.py` | Python helper that lists, creates, updates, or deletes Fabric gateway role assignments through the Fabric REST API. |
| `scripts/test_ensure_fabric_gateway_role_assignment.py` | Manual local smoke-test script for real Fabric gateway assignments. |

## Requirements

- Terraform with support for `terraform_data`.
- Python 3.12 or newer.
- `uv` for local Python environment setup.
- Azure CLI for local execution.
- A Microsoft Entra application/service principal with permission to manage the
  target Fabric gateway role assignments.
- Access to the target Fabric gateway.

For GitHub Actions, the helper can use workload identity federation/OIDC when
these values are available:

- `ACTIONS_ID_TOKEN_REQUEST_URL`
- `ACTIONS_ID_TOKEN_REQUEST_TOKEN`
- Terraform-provided `tenant_id`
- Terraform-provided `client_id`

For local runs, the helper falls back to:

```bash
az account get-access-token --resource https://api.fabric.microsoft.com
```

Run `az login` before local testing.

## Local setup

Install dependencies and create the local Python environment with `uv`:

```bash
uv sync
```

The Terraform workaround currently invokes `python3` directly from
`power-bi-rbac.tf`, so make sure `python3` resolves to Python 3.12 or newer in
the environment where `terraform apply` runs.

## Terraform usage

Copy or adapt `power-bi-rbac.tf` into the module that owns your Fabric gateway.
Then replace the TODO placeholders with values from your module.

At minimum, wire these values:

```hcl
resource "terraform_data" "sp_gateway_roles" {
  for_each = local.service_principals

  triggers_replace = {
    gateway_id     = fabric_gateway.gateway.id
    principal_id   = each.value.id
    principal_type = "ServicePrincipal"
    role           = "Admin"
    tenant_id      = module.context.tenant_id
    client_id      = module.context.client_ids[var.environment]
  }
}
```

`local.service_principals` should resolve to the service principals that need a
gateway role assignment. For example:

```hcl
locals {
  service_principals = {
    dataproduct = {
      id = "00000000-0000-0000-0000-000000000000"
    }
    datapipelines = {
      id = "11111111-1111-1111-1111-111111111111"
    }
  }
}
```

Change `role` if the service principals should receive a role other than
`Admin`.

## How the helper works

The helper calls:

```text
GET    /v1/gateways/{gatewayId}/roleAssignments
POST   /v1/gateways/{gatewayId}/roleAssignments
PATCH  /v1/gateways/{gatewayId}/roleAssignments/{assignmentId}
DELETE /v1/gateways/{gatewayId}/roleAssignments/{assignmentId}
```

Create/update flow:

1. Get a Fabric API access token.
2. List existing role assignments for the gateway.
3. Match assignments by `principal.id`.
4. Do nothing if the requested role already exists.
5. Patch the assignment if the principal exists with a different role.
6. Create a new assignment if none exists.

Destroy flow:

1. Get a Fabric API access token.
2. List existing role assignments for the gateway.
3. Delete the matching assignment if present.
4. Exit cleanly if the assignment is already absent.

## Local smoke test

The script in `scripts/test_ensure_fabric_gateway_role_assignment.py` is a
manual smoke test against real Fabric resources. Before running it, fill in:

- `TENANT_ID`
- `CLIENT_ID`
- `GATEWAY_ID`
- `SERVICE_PRINCIPALS`

Then run:

```bash
az login
uv run python scripts/test_ensure_fabric_gateway_role_assignment.py
```

To delete the smoke-test assignments:

```bash
uv run python scripts/test_ensure_fabric_gateway_role_assignment.py --delete
```

You can verify assignments in the Power BI/Fabric gateway UI:

```text
https://app.powerbi.com/groups/me/gateways?experience=power-bi
```

## Operational notes

- `terraform_data.triggers_replace` is used so changes to gateway ID, principal
  ID, principal type, role, tenant ID, or client ID force Terraform to rerun the
  provisioner.
- The helper accepts Fabric duplicate behavior by re-reading assignments after a
  failed create attempt and accepting the result if the requested assignment now
  exists.
- Destroy uses only gateway ID, principal ID, tenant ID, and client ID because it
  only needs to locate and remove the existing assignment.
- The workaround should be removed once the Fabric Terraform provider handles
  service-principal gateway role assignments consistently.

## Known limitations

- This uses Terraform provisioners, so it is a workaround rather than a fully
  declarative provider-managed resource.
- Terraform state tracks the `terraform_data` resource and trigger values, not
  the remote Fabric role assignment object itself.
- The manual smoke-test script is intended for real-environment validation, not
  isolated unit testing.
