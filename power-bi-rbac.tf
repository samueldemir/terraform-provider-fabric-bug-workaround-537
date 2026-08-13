# Use terraform_data + Fabric REST API for service-principal gateway roles.
# The microsoft/fabric provider currently returns an inconsistent
# principal.type for gateway role assignments after apply: service principals
# may be read back as either "User" or "ServicePrincipal". Terraform treats
# that as a provider consistency error before lifecycle ignore_changes can help.
# This local-exec workaround still manages the assignments idempotently, but
# bypasses the broken provider resource for the service-principal case.
resource "terraform_data" "sp_gateway_roles" {
  for_each = local.service_principals # TODO: need to be filled

  triggers_replace = {
    gateway_id     = fabric_gateway.gateway.id # TODO: need to be filled
    principal_id   = each.value.id # TODO: need to be filled
    principal_type = "ServicePrincipal"
    role           = "Admin" # TODO: need to be filled
    tenant_id      = module.context.tenant_id # TODO: need to be filled
    client_id      = module.context.client_ids[var.environment] # TODO: need to be filled
  }

  provisioner "local-exec" {
    command = join(" ", [
      "python3",
      "-u", # sichtbarkeit der stdout im tf apply
      "${path.module}/scripts/ensure_fabric_gateway_role_assignment.py",
      "--gateway-id",
      self.triggers_replace.gateway_id,
      "--principal-id",
      self.triggers_replace.principal_id,
      "--principal-type",
      self.triggers_replace.principal_type,
      "--role",
      self.triggers_replace.role,
      "--tenant-id",
      self.triggers_replace.tenant_id,
      "--client-id",
      self.triggers_replace.client_id,
    ])
  }

  provisioner "local-exec" {
    when = destroy

    command = join(" ", [
      "python3",
      "-u", # sichtbarkeit der stdout im tf apply
      "${path.module}/scripts/ensure_fabric_gateway_role_assignment.py",
      "--delete",
      "--gateway-id",
      self.triggers_replace.gateway_id,
      "--principal-id",
      self.triggers_replace.principal_id,
      "--tenant-id",
      self.triggers_replace.tenant_id,
      "--client-id",
      self.triggers_replace.client_id,
    ])
  }
}
