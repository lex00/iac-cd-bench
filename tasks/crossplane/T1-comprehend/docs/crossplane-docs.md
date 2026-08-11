# Crossplane Documentation Snippets

## Crossplane Architecture

Crossplane manages cloud infrastructure through Kubernetes-style APIs.

### Key components:
- **ProviderConfigs**: Credential configurations for cloud providers
- **XRDs**: Composite Resource Definitions that define custom APIs
- **Compositions**: Blueprints that map XRDs to managed resources
- **Claims**: User-facing resources that instantiate Compositions

### Reconciliation flow:
1. User creates a Claim
2. Crossplane matches Claim to XRD via claimNames
3. Composition transforms Claim into managed resources
4. Provider creates external cloud resources
5. Status is reported back to the Claim

## Function Pipeline Mode

Crossplane functions provide pipeline-stage transformations:
- `function-patch-and-transform`: Maps claim fields to resource specs
- `function-auto-prepare`: Adds default labels and annotations
- `function-environment-config`: Injects environment variables

## Crossplane vs Terraform

Key differences:
- Crossplane uses Kubernetes-native YAML vs Terraform's HCL
- Crossplane reconciles continuously (like Flux) vs Terraform's plan/apply
- Crossplane compositions enable composition-based abstraction
- Crossplane uses ProviderConfigs for multi-cloud support
