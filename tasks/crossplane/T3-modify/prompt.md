## Task: Add second region via provider config

**Stack:** Crossplane

### Current State

- `provider-config.yaml` defines a single `ProviderConfig` (`prod-us-east-1`, region `us-east-1`).
- `composition.yaml` provisions the S3 bucket (`s3-bucket` resource) in that
  one region via `providerConfigRef: prod-us-east-1`.
- `claim.yaml` is the existing prod claim (`AWSWebService/myapp-prod`).

### Your Task

Add a second AWS region (`us-west-2`) to the Crossplane composition without
changing existing claims:

1. Add a new `ProviderConfig` for `us-west-2` (a distinct name from `prod-us-east-1`, e.g. `prod-us-west-2`).
2. Add a new resource to `composition.yaml`'s pipeline that provisions a
   replication destination bucket via that new `ProviderConfig`, without
   modifying the existing `s3-bucket` resource entry.
3. Leave `claim.yaml` untouched.

{{scenario_spec}}
