# T1-comprehend Reference Answer Key

## Expected answers for Crossplane Composition reconciliation tracing

### Scenario: Claim changes storageGB from 20 to 50

**Q1: What happens through XRD → Composition → Provider?**
**Answer:**
1. The Claim updates spec.storageGB to 50
2. Crossplane matches the Claim to the XRD (via claimNames)
3. The Composition transforms the XRD spec into concrete resources
4. The RDS Instance resource is updated with allocatedStorage: 50
5. AWS API is called to resize the RDS instance

**Q2: Which resources get modified?**
**Answer:** The RDS Instance resource gets modified. The S3 bucket and IAM role are unaffected since only storageGB changed.

**Q3: Does the Composition need to be updated?**
**Answer:** No — the Composition defines the mapping logic. Only the Claim's spec changes trigger reconciliation.

**Q4: What is the reconciliation loop?**
**Answer:** Crossplane continuously watches Claims → matches to XRD → applies Composition → manages external resources → reports status back to Claim. This runs every reconciliation interval (default 1m).

**Q5: What if the external provider fails?**
**Answer:** Crossplane marks the Claim with a Condition showing the error. The resource enters a degraded state but Crossplane keeps retrying. The claim never reaches Ready until the external resource is healthy.
