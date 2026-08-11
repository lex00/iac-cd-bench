## Task: Trace Composition reconciliation

**Stack:** Crossplane

Given a Crossplane Composition + Claim, when the claim's `storageGB` changes from 20 to 50:
1. Trace what happens through XRD → Composition → managed resources
2. Is the RDS instance updated in-place or recreated?
3. What happens to the S3 bucket?
4. What role do `ReadinessChecks` play?
5. How does Crossplane handle the reconciliation loop?

{{scenario_spec}}
