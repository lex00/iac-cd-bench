# golden-base/chant

The chant arm of the benchmark: `scenario/SPEC.md` written as typed TypeScript
that compiles to Kubernetes manifests, in the same Flux + CAPI + ACK idiom the
`golden-base/knr-ops` column hand-writes as YAML.

The comparison this column exists to make is a narrow one. knr-ops and chant
target the *same* runtime — Flux reconciling CAPI/CAPA and ACK custom resources
into AWS. What differs is where the structure lives: knr-ops keeps it in
directory layout and kustomize patches, chant keeps it in composites and props.

## Layout

```
chant.config.ts            lexicons, environments, ownership marker, lint config
package.json               file: deps on the two vendored chant packages
vendor/                    the vendored tarballs + why they exist
.sops.yaml                 SOPS age recipient for *.sops.yaml files in this repo
age-key.txt                throwaway age identity (benchmark fixture — see
                            golden-base/knr-ops/age-key.txt for the precedent)
secrets/                   committed SOPS ciphertext (dev's DB master password)
fixtures/                  recorded lifecycle snapshot + chant search/graph
                            query output for the Phase 3 comprehension tasks
                            (see fixtures/README.md); snapshot-fixtures.sh
                            regenerates it against a throwaway kind cluster
src/
  composites/              scenario-local Composite() factories
    region-cluster.ts        RegionCluster, RegionNodePool
    secure-bucket.ts         SecureBucket
    postgres-instance.ts     PostgresInstance
    reader-iam.ts            ReaderIam
    ack-controller.ts        AckController
    defaults.ts              extracted constants (EVL009 keeps them out of factories)
    labels.ts                label/tag vocabulary, derived from props
    policies.ts              IAM policy documents + other prop shapes
    secrets.ts               consumer pointer (SecretRef) + committed-encrypted
                              provenance declaration (describeSecret/declareSecret)
    index.ts                 the public surface of the composite layer
  envs/
    dev/
      infra/main.ts          dev infra build root (bucket, DB, IAM, ACK controllers)
      clusters/main.ts       dev clusters build root (RegionCluster)
      delivery/main.ts       dev delivery build root (Flux source + Kustomizations)
    prod/
      infra/main.ts          prod infra build root
      clusters/main.ts       prod clusters build root
      delivery/main.ts       prod delivery build root
```

Each environment is three build roots, not one, because `chant build <path>`
emits one output file per invocation and the delivery layer needs three
distinct targets: the Flux `Kustomization`s that reconcile `infra/` and
`clusters/` name those paths explicitly (`FluxAppFor(..., { path:
"./dist/dev/infra" })`), and a `Kustomization` cannot reconcile a path that
contains the object declaring it. See "Build output layout" below.

## Environment isolation

**Convention: two entrypoint directories, one build root each, invoking shared
composites with per-environment props.**

`src/envs/dev` and `src/envs/prod` are separate build-root trees. Each has
three sub-roots — `infra/`, `clusters/`, `delivery/` — and `chant build
src/envs/dev/infra` sees only `src/envs/dev/infra/main.ts` and the composites
it imports, never anything under `src/envs/prod` or even under
`src/envs/dev/clusters`. The two environments share every factory and share
no build artifact, no state, and no reconciliation path.

Why this and not the alternative: chant supports build-time parameters
(`buildParams` in `chant.config.ts`, bound with `chant build --param env=prod`),
which would let one entrypoint emit either environment. That is the closer
analogue to Terraform workspaces or Pulumi stack configs — and it is the wrong
choice here, for three reasons.

1. **SPEC acceptance criterion 7 asks for structural isolation.** "Changing prod
   does not modify dev state" is a property you want the file system to
   guarantee, not a flag someone has to remember to pass. A single
   parameterized entrypoint makes `chant build` with no `--param` produce *an*
   environment, and the one it produces is whichever default the config names.
2. **The environments differ in resource set, not only in sizing.** Prod has a
   replica bucket, a replication IAM role, and a `PodIdentityAssociation` that
   dev does not have; dev has an IAM user that prod deliberately does not.
   Expressing that through a parameter means conditionals in the entrypoint —
   which is where the knr-ops column's kustomize patches already live, and
   reproducing them in TypeScript would measure the wrong thing.
3. **Two trees that read alike are the demonstration.**
   `src/envs/dev/{infra,clusters,delivery}/main.ts` and their prod
   counterparts are the same shape end to end and differ only where the SPEC
   matrix says they differ. That is legible in a way a patch file is not, and
   it is what the benchmark's comprehension tasks read.

The cost is honest and worth stating: the two entrypoint trees repeat the
call structure. What they do not repeat is the resource bodies — those live
in the composites, once.

`chant.config.ts` also declares `environments: ["dev", "prod"]`. That is a
separate thing: the identities chant threads through its operational layer
(`chant lifecycle --env prod`, the component release ledger). It does not split
the build; the directories do.

The matching row is in `scenario/SPEC.md` under "Environments".

## Build output layout

`chant build <path>` writes one file per invocation — there is no flag that
splits a single build into several output files. The delivery layer needs
three, one per `FluxAppFor`/reconciliation concern, so the source tree has
three build roots per environment and `npm run build:dev`/`build:prod` invoke
`chant build` three times each:

```
dist/
  dev/
    delivery.yaml            GitRepository + both Kustomizations (bootstrap-applied directly)
    infra/manifests.yaml     bucket(s), DBInstance, IAM, ACK HelmReleases — path "./dist/dev/infra"
    clusters/manifests.yaml  RegionCluster (CAPI/CAPA + flux2 addon)  — path "./dist/dev/clusters"
  prod/
    delivery.yaml
    infra/manifests.yaml
    clusters/manifests.yaml
```

`dist/dev/infra/manifests.yaml` and `dist/dev/clusters/manifests.yaml` are
what the two `Kustomization`s declared in `src/envs/dev/delivery/main.ts`
reconcile — their `path` props (`"./dist/dev/infra"`, `"./dist/dev/clusters"`)
name exactly these locations, so `chant lint`'s `FLUX002`/`FLUX003` checks and
the files this project actually emits now agree. `dist/dev/delivery.yaml`
holds the `GitRepository` and both `Kustomization` objects themselves — the
bootstrap edge, applied directly to the management cluster the same way
flux-system's own sync manifest is, not something a `Kustomization`
reconciles (a `Kustomization` cannot reconcile the path containing the object
that declares it).

This was `golden-base/chant`'s coverage gap #8 as scaffolded in #18: the
`FluxAppFor` paths named a layout the build did not yet emit. It is resolved
here by giving each Flux path its own build root instead of changing the
paths to match a single combined file — the three-way split is what keeps
`infra` and `clusters` independently reconcilable (and independently
`dependsOn`-orderable) once this project's `dist/` is synced into the
`myapp-infra` repository `FluxGitSource` names.

## Verifying

```bash
npm install     # resolves the two vendored tarballs
npm run verify  # typecheck + chant lint + build dev/prod + kubeconform
```

Recorded output at the time of writing:

```
> tsc --noEmit -p tsconfig.json
(no output)

> chant lint src
src/composites/secure-bucket.ts
    32:1   info   Local type "SecureBucketReplication" is used in Composite prop
                  "replication" — consider using a lexicon property type instead  COR018
✓ No problems found

> chant build src/envs/dev/delivery -f yaml -o dist/dev/delivery.yaml
fold: 0 files folded, 1 ran
> chant build src/envs/dev/infra -f yaml -o dist/dev/infra/manifests.yaml
fold: 0 files folded, 1 ran
> chant build src/envs/dev/clusters -f yaml -o dist/dev/clusters/manifests.yaml
fold: 1 file folded, 0 ran
> chant build src/envs/prod/delivery -f yaml -o dist/prod/delivery.yaml
fold: 0 files folded, 1 ran
> chant build src/envs/prod/infra -f yaml -o dist/prod/infra/manifests.yaml
fold: 0 files folded, 1 ran
> chant build src/envs/prod/clusters -f yaml -o dist/prod/clusters/manifests.yaml
fold: 1 file folded, 0 ran

> kubeconform -ignore-missing-schemas -summary dist/dev/delivery.yaml dist/dev/infra/manifests.yaml dist/dev/clusters/manifests.yaml dist/prod/delivery.yaml dist/prod/infra/manifests.yaml dist/prod/clusters/manifests.yaml
Summary: 38 resources found in 6 files - Valid: 0, Invalid: 0, Errors: 0, Skipped: 38
```

No line above says so explicitly — worth being explicit here instead: the
`chant build src/envs/dev/infra` step also writes
`dist/dev/infra/db-credentials.dev.sops.yaml`, a byte-for-byte copy of
`secrets/db-credentials.dev.sops.yaml` (see "Secrets: committed-encrypted
SOPS ciphertext" below). It is a sidecar file next to `manifests.yaml`, not a
document inside it — the `apiVersion:`-count (9) and the `-ignore-missing-schemas`
kubeconform run above are both over `manifests.yaml` alone, so the sidecar's
absence from every count and from the kubeconform target list is the point,
not an oversight: it is ciphertext, decrypted by Flux, never by kubeconform.

Per-file document counts: `dev/delivery.yaml` 3 (GitRepository + 2
Kustomizations), `dev/infra/manifests.yaml` 9, `dev/clusters/manifests.yaml`
6 (18 total, dev); `prod/delivery.yaml` 3, `prod/infra/manifests.yaml` 11
(the replica bucket and its replication role add 2 over dev),
`prod/clusters/manifests.yaml` 6 (20 total, prod). 38 across both — unchanged
from the single-file layout; the split moves resources between files, it
does not add or drop any. Committed-encrypted secrets don't change this
count either, by design (see below) — `dev/infra`'s sidecar is a seventh
*file* in `dist/`, not a 39th document.

Three notes on reading that output.

- **The one `COR018` is an `info`, and it is a deliberate divergence.**
  `SecureBucketReplication` is a narrower prop than the lexicon's
  `S3Bucket_Replication` property type on purpose: a destination ARN and a
  storage class, instead of the raw ACK `{ role, roleRef, rules }` object. Using
  the lexicon type would put the whole replication rule list back at every call
  site, which is the duplication the composite exists to remove. Info-level
  rules do not fail a build and this one is answered, not suppressed.
- **`COR001` and `COR013` are switched off in `chant.config.ts`, with the
  reasons written next to them.** COR001 ("extract every inline object to an
  exported const") is good advice for a file of hand-written resources and the
  wrong advice for a composite layer, where the spec *is* built from props at
  the call site. chant's own `cockroachdb-multi-region-gke` example makes the
  same two calls for the same two reasons.
- **All 38 documents are `skipped`, not `Valid`.** Every resource this golden
  emits is a custom resource — CAPI, CAPA, CAAPH, ACK, Flux — and
  `-ignore-missing-schemas` skips what it has no schema for. Zero errors is
  therefore a real "nothing is malformed" signal but a weak one. The strong
  check runs earlier: the k8s lexicon's `WK8501`/`WK8502` post-synth rules
  validate every custom-resource spec against the shipped CRD schema during
  `chant lint` — unknown field, wrong scalar type, value outside an enum. That
  is the check kubeconform cannot make here, and it is clean.

## Lifecycle snapshot + query fixtures

`fixtures/` holds a recorded `chant lifecycle snapshot` of this estate (dev
and prod, captured off a throwaway kind cluster with the six `dist/` files
applied — no controller needs to reconcile anything; `describeResources()`
reads the objects back through the k8s API directly) plus the
`chant lifecycle show` / `chant search --explain` / `chant graph --format
ir` output the Phase 3 comprehension tasks (iac-cd-bench#22/#24/#25) seed
from, the way the knr-ops column seeds tasks from raw YAML. `fixtures/
README.md` has the full account, including two chant CLI findings from
generating it: the k8s lexicon doesn't yet reconstruct edges for `--at`/
`--live` graphs (AWS-only today), and a real `--deep` snapshot bug in the
vendored core's orphan-branch git plumbing (worked around by using identity-
depth snapshots, which don't hit it). `fixtures/snapshot-fixtures.sh`
regenerates the whole directory from scratch; it creates and deletes its own
`chant-snap` kind cluster and touches no other cluster.

## Composite prop surfaces

The four factories epic #2 asks for, plus one that earned its place. Required
props first, then optional.

### `RegionCluster` — `src/composites/region-cluster.ts`

Members: `cluster` (`K8s::CAPI::Cluster`), `infra` (`AWSManagedCluster`),
`controlPlane` (`AWSManagedControlPlane`), `nodePool` (a nested
`RegionNodePool`), `fluxAddon` (`HelmChartProxy`).

| Prop | Type | Default |
|---|---|---|
| `name` | `string` | — |
| `env` | `string` | — |
| `region` | `string` | — |
| `availabilityZones` | `string[]` | — |
| `nodeCount` | `number` | — |
| `instanceType` | `string` | — |
| `minNodeCount` | `number` | `nodeCount` |
| `maxNodeCount` | `number` | `nodeCount` |
| `version` | `string` | `v1.31.2` |
| `publicEndpoint` | `boolean` | `false` (private-only API endpoint) |
| `associateOIDCProvider` | `boolean` | `true` |
| `fluxChartVersion` | `string` | `2.14.0` |
| `namespace` | `string` | `clusters` |
| `additionalTags` | `Record<string, string>` | — |

`RegionNodePool` is exported separately for the second-pool case: `name`,
`clusterName`, `env`, `instanceType`, `replicas`, `availabilityZones`, then
optional `minSize`, `maxSize`, `version`, `amiType`, `capacityType`,
`diskSizeGiB`, `namespace`.

An array of pools is deliberately *not* a prop. A composite factory returns a
flat record of named members, and iterating a pool array inside the factory is
exactly what `EVL010` exists to prevent. One pool per cluster is what the SPEC
asks for; a second is one more call.

### `SecureBucket` — `src/composites/secure-bucket.ts`

Members: `bucket` (`K8s::S3::Bucket`), `replicaRole` (`K8s::Iam::Role`, only
when `replication` is set).

| Prop | Type | Default |
|---|---|---|
| `name` | `string` | — |
| `env` | `string` | — |
| `region` | `string` | — |
| `kmsKeyARN` | `string` | unset → SSE-S3 (AES-256) |
| `replication` | `{ destinationBucketARN, storageClass?, prefix?, replicateExisting? }` | unset |
| `namespace` | `string` | `infra` |
| `component` | `string` | `assets` |

Versioning, encryption, public-access block, and bucket-owner-enforced
ownership are not props. There is no call that produces a bucket without them.

### `PostgresInstance` — `src/composites/postgres-instance.ts`

Members: `instance` (`K8s::Rds::DBInstance`).

| Prop | Type | Default |
|---|---|---|
| `name` | `string` | — |
| `env` | `string` | — |
| `instanceClass` | `string` | — |
| `databaseName` | `string` | — |
| `masterUsername` | `string` | — |
| `masterPassword` | `SecretRef` | — |
| `dbSubnetGroupName` | `string` | — |
| `allocatedStorageGiB` | `number` | `20` |
| `maxAllocatedStorageGiB` | `number` | unset |
| `engineVersion` | `string` | `16.4` |
| `multiAZ` | `boolean` | `false` |
| `storageEncrypted` | `boolean` | `true` |
| `kmsKeyID` | `string` | unset → AWS-managed key |
| `backupRetentionDays` | `number` | `7`; below 7 throws |
| `vpcSecurityGroupIDs` | `string[]` | unset |
| `namespace` | `string` | `infra` |
| `component` | `string` | `database` |

`deletionProtection: true` and `publiclyAccessible: false` are pinned, not
props.

### `ReaderIam` — `src/composites/reader-iam.ts`

Members: `policy` (`K8s::Iam::Policy`), `role` (`K8s::Iam::Role`), `user`
(`K8s::Iam::User`, when `programmaticAccess`), `podIdentity`
(`K8s::Eks::PodIdentityAssociation`, when `podIdentity` is set).

| Prop | Type | Default |
|---|---|---|
| `name` | `string` | — |
| `env` | `string` | — |
| `bucketName` | `string` | — |
| `trust` | `{ mode: "account", accountID, externalID? }` or `{ mode: "oidc", providerARN, issuerHost, serviceAccountNamespace, serviceAccountName }` | — |
| `prefix` | `string` | unset → whole bucket |
| `additionalActions` | `string[]` | unset |
| `programmaticAccess` | `boolean` | `false` |
| `podIdentity` | `{ clusterName, serviceAccountNamespace, serviceAccountName }` | unset |
| `maxSessionDurationSeconds` | `number` | `3600` |
| `namespace` | `string` | `infra` |
| `component` | `string` | `identity` |

`additionalActions` is a list of enumerated actions. There is no prop that
appends a wildcard, and the `oidc` trust arm pins both the service-account
`:sub` and the `:aud` — pinning only `:aud` is the IRSA over-trust that lets
every service account in the cluster assume the role.

### `AckController` — `src/composites/ack-controller.ts`

Members: `release` (`K8s::Flux::HelmRelease`).

| Prop | Type | Default |
|---|---|---|
| `service` | `string` (`s3`, `rds`, `iam`) | — |
| `env` | `string` | — |
| `region` | `string` | — |
| `chartVersion` | `string` | — |
| `repositoryName` | `string` | — |
| `interval` | `string` | `10m` |
| `dependsOn` | `{ name, namespace? }[]` | unset |
| `replicas` | `number` | `1` |
| `targetNamespace` | `string` | `ack-system` |

A fifth composite beyond the four epic #2 names. It earns its place on the same
argument: without it each environment repeats three near-identical 20-line
`HelmRelease` bodies, which is the duplication this column exists to remove.

## Secrets: committed-encrypted SOPS ciphertext

Nothing secret-shaped is in this directory as *cleartext*, and nothing
secret-shaped is in the primary build output. dev's RDS master password now
mirrors what `golden-base/knr-ops` does: it is genuine SOPS ciphertext,
committed at `secrets/db-credentials.dev.sops.yaml` and decrypted by Flux
directly into the cluster — chant itself never sees the plaintext, at build
time or any other time.

```
.sops.yaml                              # age recipient, path_regex \.sops\.ya?ml$
age-key.txt                             # throwaway age identity — a benchmark
                                         #   fixture, mirroring knr-ops/age-key.txt
secrets/db-credentials.dev.sops.yaml    # committed ciphertext: metadata cleartext,
                                         #   data/stringData ENC[...]
```

`age-key.txt`'s private key never leaves this file — it is not read by any
`chant` code path, only by `sops -d` when a human or Flux's `sops-age` Secret
needs to decrypt. Regenerating: `age-keygen -o age-key.txt`, then update the
recipient in `.sops.yaml`, then `sops -e --age <recipient> --encrypted-regex
'^(data|stringData)$' -i secrets/db-credentials.dev.sops.yaml` (after editing
its `stringData` back to plaintext first — `sops -e` on an already-encrypted
file is a no-op on the already-`ENC[`-shaped values).

`src/composites/secrets.ts`'s `describeSecret()` — until now a hand-rolled
string formatter, the structural stand-in this arm used while
`declareSecret()` was unpublished — now makes the real call:

```ts
export const dbMasterPassword = describeSecret({
  name: "myapp-dev-db-master",
  file: "secrets/db-credentials.dev.sops.yaml",
  keys: ["password"],
});
```

declared in `src/envs/dev/infra/main.ts` alongside the `PostgresInstance` call
that consumes the same name via `secretRef()`. Two chant mechanisms make the
claim load-bearing, not decorative:

- **WK8504** — the k8s lexicon's `buildRoots()` hook reads
  `secrets/db-credentials.dev.sops.yaml` at build time and refuses the build
  if it does not resolve: wrong `metadata.name`, no `sops` block, or a
  `data`/`stringData` value that isn't `ENC[...]`-shaped (the "edited the file
  and forgot to re-encrypt" failure). Verified live for this golden — see
  "Gates verified" below.
- **WK8503** — a resolved committed-encrypted declaration joins the set of
  Secrets the build *produces* (namespace-matched, same as a literal `Secret`
  manifest), not the set of provenance the check merely takes a human's word
  for. This golden declares no application workload (coverage gap 5), so
  WK8503 has no pod spec to check against it either way — the producer-set
  membership is real but unexercised here; a lexicon end-to-end test exercises
  it (`bench/sops-impl`, `lexicons/k8s/src/lint/post-synth/post-synth.test.ts`).

On resolution, the ciphertext bytes are copied — not re-serialized, no key
sorting, no `sops` binary invoked — into `SerializerResult.files`, which the
k8s serializer routes to a sidecar next to the primary manifest:
`dist/dev/infra/db-credentials.dev.sops.yaml`, byte-identical to the committed
source. It is never a document inside `manifests.yaml`; chant's own appliers
read the primary output only, so "chant pushes an undecrypted Secret into a
cluster" is structurally impossible, not merely unlikely.

**prod's master password is deliberately still `referenced`** — created out
of band by the platform runbook, the same as both environments were before
this change (`src/envs/prod/infra/main.ts`). Flipping one environment is the
demonstration; flipping both would double the ciphertext-maintenance surface
of this README's worked example for no comprehension-task benefit distinct
from dev's.

**The delivery side is not wired, on purpose.** `spec.decryption` is already
in the generated typed surface (`K8s::Flux::Kustomization.decryption`, pulled
from the pinned flux2 CRD schema), but the lexicon's `FluxAppFor` composite
(`src/envs/dev/delivery/main.ts` calls it) does not yet expose a `decryption`
prop to set it — that pass-through is iac-cd-bench#33, landing separately and
in parallel with this change. So `myapp-dev-infra`'s `Kustomization` reconciles
`./dist/dev/infra` — which, as of this change, contains a SOPS-encrypted
sidecar — with no `spec.decryption` block naming the age identity Flux would
need to decrypt it. That is an honest gap in this golden today, not a bug in
what shipped here: when #33's re-vendor lands, wiring
`decryption: "sops"` (defaulting `secretRef.name` to `sops-age`, per the
design doc) onto `infraApp` in `src/envs/dev/delivery/main.ts` is the fix, and
a new WK8505 warning ("committed-encrypted secret with no Flux decryption
wiring in this build") may start firing on this golden's `dev/infra` build
until that composite prop is added there too — expected wiring surfacing a
real gap, not a regression to chase down.

Chant's four-way secret-provenance taxonomy (`referenced`, `from-provider`,
`generated-once`, `committed-encrypted`) is what makes both of the above
precise instead of hand-waved: `referenced` is exactly what prod's master
password still is, and the eventual `sops-age` Secret in `flux-system` that
Flux's own decryption needs is itself a `referenced` declaration
(`declareSecret({ name: "sops-age", provenance: "referenced", scope:
"flux-system, injected at bootstrap" })`) — bootstrap-injected, never in git,
the same shape as everything else this repo doesn't hold.

`src/composites/secrets.ts` still carries `SecretRef` — the
`{ name, namespace, key }` / `{ name }` pointer shapes ACK and Flux consumers
need — unchanged, and unrelated to provenance: a consumer's pointer looks the
same whether the Secret it names is referenced or committed-encrypted. See the
file's own doc comment for the split between "where does a consumer point"
and "where did the value come from."

## Coverage gaps

Findings, not excuses. Each is something the scenario needs that this
toolchain cannot declare today, with what was done instead.

### 1. `declareSecret` — shipped, still not in the published core

This is now a shipped capability pending only upstream publish, not an open
implementation gap. `declareSecret()`, all four provenance kinds including
`committed-encrypted`, and the k8s lexicon's WK8503/WK8504 coverage for it are
on chant's `bench/sops-impl` branch (`5ad19f9a`) and vendored here (see
`vendor/README.md`) — `src/composites/secrets.ts`'s `describeSecret()` makes
the real `declareSecret({ provenance: "committed-encrypted" })` call for dev's
master password (see "Secrets: committed-encrypted SOPS ciphertext" above).
What remains open is purely upstream: none of this is in the published
`@intentius/chant@0.46.0` / `@intentius/chant-lexicon-k8s@0.47.0`, which is why
`vendor/` still exists at all. A golden that depends on an unpublished API in
two packages instead of one is a worse artifact than one that keeps discipline
structurally where it must — which is exactly why prod's master password
stays `referenced` via the same hand-rolled-shaped `SecretRef` pointer rather
than every ref in this repo needing the vendored primitive to type-check;
`describeSecret()`'s new signature is the one line that changes when both
packages publish, same as before.

Also still open, and unrelated to publishing: the Flux decryption
pass-through (iac-cd-bench#33 — `FluxAppFor`'s `decryption` prop) is not yet
in any vendored build, chant's own or otherwise. See "Secrets:
committed-encrypted SOPS ciphertext" above.

### 2. The vendored lexicon does not work with the published core

Not a scenario gap — a toolchain one, and the reason `vendor/` has two tarballs
instead of the one the plan called for. `chant-lexicon-k8s@0.47.0`'s `wk8503`
post-synth rule imports `@intentius/chant/secret-provenance`, which
`@intentius/chant@0.46.0` does not ship. `chant lint` fails at module
resolution before reading a single source file. Vendoring the matching core
build is the only fix short of patching the lexicon.

### 3. ACK RDS coverage is `DBInstance` only

No `DBSubnetGroup` kind exists in the lexicon, so the subnet group is a
`dbSubnetGroupName` *prop* pointing at something created elsewhere rather than
a declared member. The knr-ops column declares its subnet group as a resource.
Same for `DBParameterGroup`.

### 4. ACK IAM coverage has no `AccessKey`

The SPEC's dev arm is "IAM user + programmatic access". The user is declared;
the access key is not, because `iam.services.k8s.aws` in this lexicon covers
`Role`, `User`, and `Policy` only. Policy *attachment* is fine — ACK models it
as `policyRefs` on the Role and User, so there is no `PolicyAttachment` kind to
miss.

### 5. Nothing declares the HTTPS exposure row

SPEC row 5 (internal ALB or CloudFront in dev, CloudFront + ACM in prod) and
acceptance criterion 6 (443 listener, valid cert reference) have no typed kind
in this lexicon for the cloud half: no ACK `acm`, no ACK `cloudfront`, no ACK
`elbv2`. The certificate and the CDN are not declarable here, full stop.

The in-cluster half *is* declarable — the lexicon ships a native `Ingress`
type and a pre-built `AlbIngress` composite (`certificateArn`, `scheme:
"internal" | "internet-facing"`, `sslRedirect`) that would type an ALB-backed
Ingress cleanly. It is deliberately not called here. `golden-base/knr-ops`
was checked (`infra/app/deployment.yaml`) as the directive for this arm
requires: its application `Service` is `type: ClusterIP` with no `Ingress`,
no ALB, no CloudFront, and no ACM object anywhere in that column. This arm
mirrors that scope rather than reaching past it — a golden that types more
of the HTTPS row than its comparison column declares would be measuring
lexicon coverage, not scenario parity, and the two columns exist to be
compared. Both stop at the same place: the in-cluster Service (knr-ops
declares one; this arm declares no application workload at all, since
SPEC's "Not in Scope" list excludes application code and neither the SPEC
row nor epic #2's composite list asks for one). The certificate, the load
balancer, and the CDN are the finding — on both columns — not a chant-only
gap.

### 6. Networking is referenced, never declared

VPCs, subnets, and security groups are string props (`sg-dev-database`,
`myapp-dev-subnets`). No ACK `ec2` kinds are in the lexicon. CAPA can create a
managed VPC for the cluster, which is what `AWSManagedControlPlane` does here,
but the ACK resources' networking is assumed to exist. knr-ops has the same
shape, so the comparison is fair — but neither column *declares* the network.

### 7. CRD-generated classes are typed at the top level only

`new CAPICluster({ metadata, spec })` types `spec` as
`Record<string, unknown>`. The real checking happens after synthesis, in
`WK8501`/`WK8502`, against the shipped CRD schema — which does catch a
misspelled field, a wrong scalar type, and an out-of-enum value, but catches it
at lint time rather than in the editor. The composite prop surfaces above are
where the compile-time typing actually lives, which is an argument for the
composite layer rather than against it.

Former gap 8 — delivery paths naming an output layout the build did not
emit — is resolved; see "Build output layout" above.

## Toolchain

| Piece | Version | Source |
|---|---|---|
| `@intentius/chant` | 0.46.0 (branch build, `bench/sops-impl` @ `5ad19f9a`) | `vendor/intentius-chant-0.46.0-bench.tgz` |
| `@intentius/chant-lexicon-k8s` | 0.47.0 (branch build, `bench/sops-impl` @ `5ad19f9a`) | `vendor/intentius-chant-lexicon-k8s-0.47.0.tgz` |
| `sops` | 3.13.3 | system (`sops -e`/`-d` on `secrets/*.sops.yaml`; not invoked by `chant` itself) |
| `age` | 1.3.1 | system (`age-keygen` minted `age-key.txt`) |
| `kubeconform` | 0.7.0 | system |
| Node | 24.x (20.x per `mise.toml` also works) | system |

Both `file:` dependencies flip to registry versions once upstream publishes —
see `vendor/README.md`.
