# vendor/

Two chant packages are pinned here as tarballs instead of resolved from npm.
**Both flip to plain registry versions once upstream publishes**, and the
`file:` entries in `../package.json` are the only lines that change.

| Tarball | Package | Why it is vendored |
|---|---|---|
| `intentius-chant-lexicon-k8s-0.47.0.tgz` | `@intentius/chant-lexicon-k8s` | Carries the CAPI/CAPA/ACK typed kinds this golden is written against (`K8s::CAPI::Cluster`, `K8s::Controlplane::AWSManagedControlPlane`, `K8s::Infrastructure::AWSManagedCluster` / `AWSManagedMachinePool`, `K8s::Addons::HelmChartProxy` / `ClusterResourceSet`, `K8s::S3::Bucket`, `K8s::Rds::DBInstance`, `K8s::Iam::Role` / `User` / `Policy`, `K8s::Eks::PodIdentityAssociation`). The published 0.46.0 lexicon has none of them. Built from chant branch `bench/lexicon-capi-ack` at `89648046`. |
| `intentius-chant-0.46.0-bench.tgz` | `@intentius/chant` | Not the plan, and not optional. The lexicon above imports `@intentius/chant/secret-provenance` from its `wk8503` post-synth rule, and that module does not exist in the published `@intentius/chant@0.46.0` — `chant lint` dies with `Cannot find module .../src/secret-provenance.ts` before it reaches a single source file. Same branch, same commit, `npm run build` then `npm pack`. The filename carries a `-bench` suffix because the version inside is also `0.46.0`; it is *not* the registry 0.46.0. |

## Rebuilding them

From a chant checkout on `bench/lexicon-capi-ack`:

```bash
cd packages/core       && npm run build && npm pack --ignore-scripts
cd ../../lexicons/k8s  && npm pack --ignore-scripts
```

Copy the two tarballs here, renaming the core one to
`intentius-chant-0.46.0-bench.tgz`, then `npm install` in the parent directory.

## Flipping to the registry

When both packages publish with the CAPI/CAPA/ACK kinds and the
secret-provenance module, replace the two `file:` entries in `package.json`
with version ranges, delete this directory, and re-run `npm run verify`. No
source file should need to change.
