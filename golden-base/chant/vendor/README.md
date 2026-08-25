# vendor/

Two chant packages are pinned here as tarballs instead of resolved from npm.
**Both flip to plain registry versions once upstream publishes**, and the
`file:` entries in `../package.json` are the only lines that change.

| Tarball | Package | Why it is vendored |
|---|---|---|
| `intentius-chant-lexicon-k8s-0.47.0.tgz` | `@intentius/chant-lexicon-k8s` | Carries the CAPI/CAPA/ACK typed kinds this golden is written against (`K8s::CAPI::Cluster`, `K8s::Controlplane::AWSManagedControlPlane`, `K8s::Infrastructure::AWSManagedCluster` / `AWSManagedMachinePool`, `K8s::Addons::HelmChartProxy` / `ClusterResourceSet`, `K8s::S3::Bucket`, `K8s::Rds::DBInstance`, `K8s::Iam::Role` / `User` / `Policy`, `K8s::Eks::PodIdentityAssociation`), the `committed-encrypted` secret provenance kind end to end (`declareSecret({ provenance: "committed-encrypted", file })`'s resolution/emission path (`sops/encrypted-secret-file.ts`), WK8503, WK8504), **and, as of this build, the Flux decryption pass-through**: `FluxAppFor`'s `decryption?: "sops" | { provider: "sops"; secretRef?: string }` option (`composites/flux-app.ts`, defaults `secretRef.name` to `sops-age`) and WK8505 (warns when a build's Kustomizations set no `spec.decryption` but the same build also resolved a committed-encrypted secret). Built from chant branch `bench/flux-sops` at `b7324024` (which sits on top of `bench/sops-impl`'s `5ad19f9a` — same CAPI/CAPA/ACK + SOPS surface, plus three commits: `BuildRootContext` carrying discovered entities to the plugin's `buildRoots()` hook, the `decryption` pass-through itself, and WK8505). |
| `intentius-chant-0.46.0-bench.tgz` | `@intentius/chant` | Not the plan, and not optional. The lexicon above imports `@intentius/chant/secret-provenance` from its `wk8503`/`wk8504` post-synth rules, and that module does not exist in the published `@intentius/chant@0.46.0` — `chant lint` dies with `Cannot find module .../src/secret-provenance.ts` before it reaches a single source file. Same branch (`bench/flux-sops`, `b7324024`), `npm run build` then `npm pack`. The filename carries a `-bench` suffix because the version inside is also `0.46.0`; it is *not* the registry 0.46.0. `declareSecret({ provenance: "committed-encrypted" })` itself lives here (`src/secret-provenance.ts`), unchanged since the prior vendoring — this re-pack is a superset because the k8s lexicon's `BuildRootContext.entities` widening reads through it. |

## Rebuilding them

From a chant checkout on `bench/flux-sops` (or whatever branch has since absorbed it):

```bash
cd packages/core       && npm run build && npm pack --ignore-scripts
cd ../../lexicons/k8s  && npm run build && npm pack --ignore-scripts
```

Copy the two tarballs here, renaming the core one to
`intentius-chant-0.46.0-bench.tgz`, then in the parent directory delete
`node_modules/` **and `package-lock.json`** before `npm install`. Both
tarballs keep the same filename and package `version` across a re-pack, and
npm's `file:` resolution caches by the integrity hash recorded in
`package-lock.json` rather than by reading the tarball's bytes again — a
plain `npm install` (even after `rm -rf node_modules`) silently keeps
serving the OLD tarball's content out of that cache if the lockfile isn't
also removed. This bit the `bench/flux-sops` re-vendor: `npm install` alone
reported "added N packages" and looked like a clean install, but
`node_modules/@intentius/chant-lexicon-k8s/src/lint/post-synth/` still had
no `wk8505.ts` until `package-lock.json` was deleted too.

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
file, and iac-cd-bench issues #6/#16/#32). The second vendoring
(`bench/sops-impl` at `5ad19f9a`) was a superset: same CAPI/CAPA/ACK surface,
plus the fourth provenance kind and its WK8503/WK8504 lint coverage.
`src/composites/secrets.ts`'s `describeSecret` started making the real
`declareSecret({ provenance: "committed-encrypted" })` call at that point —
see README, "Secrets: committed-encrypted SOPS ciphertext".

This third vendoring (`bench/flux-sops` at `b7324024`, iac-cd-bench#33) is
again a superset: same CAPI/CAPA/ACK + SOPS-provenance surface, plus
`FluxAppFor`'s `decryption` pass-through and WK8505. It is what lets
`src/envs/dev/delivery/main.ts` wire `decryption: "sops"` onto `infraApp` —
see README, "Secrets: committed-encrypted SOPS ciphertext" for the wiring
itself and what WK8505 does and does not catch given this project's
three-way build-root split.
