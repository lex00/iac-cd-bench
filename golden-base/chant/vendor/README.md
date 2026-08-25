# vendor/

Two chant packages are pinned here as tarballs instead of resolved from npm.
**Both flip to plain registry versions once upstream publishes**, and the
`file:` entries in `../package.json` are the only lines that change.

| Tarball | Package | Why it is vendored |
|---|---|---|
| `intentius-chant-lexicon-k8s-0.47.0.tgz` | `@intentius/chant-lexicon-k8s` | Carries the CAPI/CAPA/ACK typed kinds this golden is written against (`K8s::CAPI::Cluster`, `K8s::Controlplane::AWSManagedControlPlane`, `K8s::Infrastructure::AWSManagedCluster` / `AWSManagedMachinePool`, `K8s::Addons::HelmChartProxy` / `ClusterResourceSet`, `K8s::S3::Bucket`, `K8s::Rds::DBInstance`, `K8s::Iam::Role` / `User` / `Policy`, `K8s::Eks::PodIdentityAssociation`) **and, as of this build, the `committed-encrypted` secret provenance kind end to end**: `declareSecret({ provenance: "committed-encrypted", file })`'s resolution/emission path (`sops/encrypted-secret-file.ts`), WK8503 satisfied through the producer set (a resolved committed-encrypted declaration counts as a Secret the build produces), and WK8504 (the ciphertext-shape check: file resolves, is the named `v1` `Secret`, carries a `sops` block, every `data`/`stringData` value is `ENC[...]`-shaped). Built from chant branch `bench/sops-impl` at `5ad19f9a` (which sits on top of `bench/lexicon-capi-ack`'s `89648046` — same CAPI/CAPA/ACK kinds, plus the five SOPS commits: design doc, the `committed-encrypted` provenance kind, `BuildRootContext.entities` widening, the sidecar resolution/emission path, WK8503/WK8504). |
| `intentius-chant-0.46.0-bench.tgz` | `@intentius/chant` | Not the plan, and not optional. The lexicon above imports `@intentius/chant/secret-provenance` from its `wk8503`/`wk8504` post-synth rules, and that module does not exist in the published `@intentius/chant@0.46.0` — `chant lint` dies with `Cannot find module .../src/secret-provenance.ts` before it reaches a single source file. Same branch (`bench/sops-impl`, `5ad19f9a`), `npm run build` then `npm pack`. The filename carries a `-bench` suffix because the version inside is also `0.46.0`; it is *not* the registry 0.46.0. This build is also where `declareSecret({ provenance: "committed-encrypted" })` itself lives (`src/secret-provenance.ts`) — the earlier vendored tarball only had `referenced` / `from-provider` / `generated-once`. |

## Rebuilding them

From a chant checkout on `bench/sops-impl` (or whatever branch has since absorbed it):

```bash
cd packages/core       && npm run build && npm pack --ignore-scripts
cd ../../lexicons/k8s  && npm pack --ignore-scripts
```

Copy the two tarballs here, renaming the core one to
`intentius-chant-0.46.0-bench.tgz`, then `npm install` in the parent directory.

## Flipping to the registry

When both packages publish with the CAPI/CAPA/ACK kinds and the
secret-provenance module (including `committed-encrypted`), replace the two
`file:` entries in `package.json` with version ranges, delete this directory,
and re-run `npm run verify`. No source file should need to change.

## History

The first vendoring (`bench/lexicon-capi-ack` at `89648046`) shipped the
CAPI/CAPA/ACK kinds and `referenced`/`from-provider`/`generated-once` secret
provenance only — `committed-encrypted` was not implemented upstream yet, so
`src/composites/secrets.ts` carried a hand-rolled `SecretRef` structural
stand-in instead of a real `declareSecret()` call (see git history on that
file, and iac-cd-bench issues #6/#16/#32). This re-pack from `bench/sops-impl`
is a superset: same CAPI/CAPA/ACK surface, plus the fourth provenance kind and
its WK8503/WK8504 lint coverage. `src/composites/secrets.ts`'s `describeSecret`
now makes the real `declareSecret({ provenance: "committed-encrypted" })` call
— see README, "Secrets: committed-encrypted SOPS ciphertext".
