
# NOTE: This is not really a test. But you can test it locally by running python and check online
# on https://app.powerbi.com/groups/me/gateways?experience=power-bi
# Please fill the VARIABLES below for running.
from ensure_fabric_gateway_role_assignment import ensure_assignment


# Local dev test values.
# Run `az login` first; locally the helper falls back to Azure CLI auth.
TENANT_ID = "<TOADD>"
CLIENT_ID = "<TOADD>"

# Fill these manually before running.
GATEWAY_ID = "<TOADD>"

# Use these for dev
SERVICE_PRINCIPALS = {
    "dataproduct": "<TOADD>",
    "datapipelines": "<TOADD>"
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete", action="store_true", help="Delete the test gateway role assignments.")
    args = parser.parse_args()

    for name, principal_id in SERVICE_PRINCIPALS.items():
        if args.delete:
            print(f"Deleting gateway Admin role for {name}: {principal_id}")
            delete_assignment(
                gateway_id=GATEWAY_ID,
                principal_id=principal_id,
                tenant_id=TENANT_ID,
                client_id=CLIENT_ID,
            )
        else:
            print(f"Ensuring gateway Admin role for {name}: {principal_id}")
            ensure_assignment(
                gateway_id=GATEWAY_ID,
                principal_id=principal_id,
                principal_type="ServicePrincipal",
                role="Admin",
                tenant_id=TENANT_ID,
                client_id=CLIENT_ID,
            )


if __name__ == "__main__":
    main()
