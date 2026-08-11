# T5-review Reference Answer Key — same as Pulumi Python

Crossplane review should flag:
1. `deletionPolicy: Delete` added provider-wide (destroys all managed resources on claim deletion)
2. Bucket versioning dropped (no recovery from deletions)
3. Missing ProviderConfig (no credentials → reconciliation fails)
4. Composition referencing wrong fromFieldPath (never reconciles correctly)

Pulumi TypeScript review has same issues as Python variant.
