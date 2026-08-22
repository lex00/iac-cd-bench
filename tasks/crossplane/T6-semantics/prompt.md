## Task: Semantic prediction quiz — Crossplane composition behavior

**Stack:** crossplane (XRDs + Compositions + managed resources)

You are given an XRD, a Composition, and a claim (below / in the workspace).
Answer questions about what Crossplane will ACTUALLY do at runtime.

### Repo files

- `xrds/xwebservice.yaml` — XRD `xwebservices.platform.example.org` (claim kind `WebService`)
- `compositions/webservice-aws.yaml` — Composition `webservice-aws` with three composed resources
- `claims/storefront.yaml` — claim `storefront` in namespace `team-a`

### Questions

Q1. `kubectl delete webservice storefront -n team-a` runs and finishes. Are
the composed Kubernetes managed-resource objects (Bucket, Role,
RolePolicyAttachment) deleted from the cluster?

Q2. After Q1 completes, does the S3 bucket `storefront-artifacts-prod` still
exist in AWS? Answer from the Bucket's spec as written.

Q3. After Q1 completes, does the IAM role still exist in AWS? Answer from the
Role's spec as written.

Q4. The platform team updates the `webservice-aws` Composition, which creates
a new CompositionRevision. Does the `storefront` claim start using the new
revision automatically?

Q5. Where does the connection secret for this claim end up: name AND
namespace? (Consider both `writeConnectionSecretsToNamespace` on the
Composition and `writeConnectionSecretToRef` on the claim — which one governs
the secret the app team reads?)

Q6. Crossplane creates the three composed resources. Does it create them
sequentially in the order listed in the Composition, waiting for each to be
ready before the next (like Flux dependsOn), or does it create them all and
converge by re-reconciling?

Q7. Claim vs composite: which object is namespaced and which is
cluster-scoped? Answer for `WebService` (claim) and `XWebService` (XR).

### Answer format

Return ONLY a fenced JSON code block named `answers.json` in exactly this
shape:

```json
{
  "q1": "deleted | kept",
  "q2": "exists | deleted",
  "q3": "exists | deleted",
  "q4": "automatic | manual",
  "q5": {"name": "<secret-name>", "namespace": "<namespace>"},
  "q6": "sequential | parallel-converge",
  "q7": {"claim": "namespaced | cluster-scoped", "xr": "namespaced | cluster-scoped"}
}
```

### Context Files

{{scenario_spec}}
