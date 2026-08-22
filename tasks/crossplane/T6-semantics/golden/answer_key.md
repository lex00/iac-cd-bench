# Golden answers — crossplane T6-semantics

```json
{
  "q1": "deleted",
  "q2": "exists",
  "q3": "deleted",
  "q4": "manual",
  "q5": {"name": "storefront-conn", "namespace": "team-a"},
  "q6": "parallel-converge",
  "q7": {"claim": "namespaced", "xr": "cluster-scoped"}
}
```

## Rationale

- **q1**: Deleting a claim cascades: claim → XR → composed managed resources. All three MR objects are deleted from the cluster.
- **q2**: The Bucket has `deletionPolicy: Orphan` — the external AWS bucket is orphaned and survives.
- **q3**: The Role has `deletionPolicy: Delete` — the external IAM role is deleted.
- **q4**: The claim sets `compositionUpdatePolicy: Manual` — it stays pinned to its current CompositionRevision until manually bumped.
- **q5**: The claim's `writeConnectionSecretToRef` (name `storefront-conn`) produces the app-facing secret in the claim's own namespace `team-a`. (`writeConnectionSecretsToNamespace` only governs the XR-level secret in `crossplane-system`.)
- **q6**: Crossplane composes all resources and converges through repeated reconciliation — there is no sequential dependsOn ordering.
- **q7**: Claims are namespaced; composite resources (XRs) are cluster-scoped.
