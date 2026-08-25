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
    secrets.ts               referenced-secret plumbing (the SOPS interim)
    index.ts                 the public surface of the composite layer
  envs/
    dev/main.ts              dev build root
    prod/main.ts             prod build root
```

## Environment isolation

**Convention: two entrypoint directories, one build root each, invoking shared
composites with per-environment props.**

`src/envs/dev` and `src/envs/prod` are separate build roots. `chant build
src/envs/dev` sees `src/envs/dev/main.ts` and the composites it imports, and
never sees anything under `src/envs/prod`. The two environments share every
factory and share no build artifact, no state, and no reconciliation path.

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
3. **Two files that read alike are the demonstration.** `src/envs/dev/main.ts`
   and `src/envs/prod/main.ts` are the same shape end to end and differ only
   where the SPEC matrix says they differ. That is legible in a way a patch
   file is not, and it is what the benchmark's comprehension tasks read.

The cost is honest and worth stating: the two entrypoints repeat the call
structure. What they do not repeat is the resource bodies — those live in the
composites, once.

`chant.config.ts` also declares `environments: ["dev", "prod"]`. That is a
separate thing: the identities chant threads through its operational layer
(`chant lifecycle --env prod`, the component release ledger). It does not split
the build; the directories do.

The matching row is in `scenario/SPEC.md` under "Environments".

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

> chant build src/envs/dev  -f yaml -o dist/dev.yaml
fold: 0 files folded, 1 ran
> chant build src/envs/prod -f yaml -o dist/prod.yaml
fold: 0 files folded, 1 ran

> kubeconform -ignore-missing-schemas -summary dist/dev.yaml dist/prod.yaml
Summary: 38 resources found in 2 files - Valid: 0, Invalid: 0, Errors: 0, Skipped: 38
```

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

## Secrets: the SOPS interim

Nothing secret-shaped is in this directory, and nothing secret-shaped is in the
build output. The RDS master password and the application's DB connection
string both live in Kubernetes Secrets created out of band; the `DBInstance`
points at the first by name/namespace/key, and the application consumes the
second the same way.

That is chant's **referenced provenance**: the value exists out of band, a human
or an external process put it where consumers read it, and the estate records
only that it depends on it. It is the closest of chant's three provenance kinds
(`referenced`, `from-provider`, `generated-once`) to what the knr-ops column
does with SOPS — and it is not the same thing. Committed ciphertext is a fourth
taxonomy row with no primitive yet; that gap is tracked as the SOPS-gap issue,
and it is why this column cannot mirror `golden-base/knr-ops/.sops.yaml`.

`src/composites/secrets.ts` carries a `SecretRef` type with no field that could
hold material, plus the two shapes consumers need (ACK's
`{ name, namespace, key }` and Flux's `{ name }`). When
`declareSecret({ provenance: "referenced" })` publishes, `describeSecret()`
becomes a `declareSecret()` call and every ref keeps working unchanged — see
the first coverage gap below.

## Coverage gaps

Findings, not excuses. Each is something the scenario needs that this
toolchain cannot declare today, with what was done instead.

### 1. `declareSecret` is not in the published core

The binding directive for this arm was to use
`declareSecret({ provenance: "referenced" })` for the DB secret. The primitive
is on chant's main branch (`e5ca9f63`, core #1828) and is **not** in the
published `@intentius/chant@0.46.0`, which is the newest version on the
registry. It is in the vendored core tarball, so it is technically reachable —
but a golden that depends on an unpublished API in *two* packages instead of
one is a worse artifact than one that keeps the discipline structurally. So the
provenance is enforced by construction (`SecretRef` has no material-bearing
field) and the primitive call is a one-line change when it ships.

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
in this lexicon: no ACK `acm`, no ACK `cloudfront`, no ACK `elbv2`. The
in-cluster half is declarable (an `Ingress` with ALB controller annotations, or
a Gateway API `Gateway` + `HTTPRoute`, both typed); the certificate and the CDN
are not. This is the largest single gap and it lands squarely on the full SPEC
implementation, not on the composites.

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

### 8. Delivery paths point at an output layout that does not exist yet

`FluxAppFor(..., { path: "./dist/dev/infra" })` names a directory the build
does not currently emit — `chant build -o` writes one file per invocation, so
today's output is `dist/dev.yaml` and `dist/prod.yaml`. The path split is the
shape the full SPEC implementation should emit into; wiring it is that issue's
work, not the scaffold's. `FLUX002`/`FLUX003` still validate the `sourceRef`
and `dependsOn` edges, and both are clean.

## Toolchain

| Piece | Version | Source |
|---|---|---|
| `@intentius/chant` | 0.46.0 (branch build) | `vendor/intentius-chant-0.46.0-bench.tgz` |
| `@intentius/chant-lexicon-k8s` | 0.47.0 (branch build) | `vendor/intentius-chant-lexicon-k8s-0.47.0.tgz` |
| `kubeconform` | 0.7.0 | system |
| Node | 24.x (20.x per `mise.toml` also works) | system |

Both `file:` dependencies flip to registry versions once upstream publishes —
see `vendor/README.md`.
