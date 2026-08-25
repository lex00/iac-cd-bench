/**
 * dev environment — build root.
 *
 * `chant build src/envs/dev` sees this file and nothing under src/envs/prod.
 * The two environments share every composite and share no build, which is what
 * makes SPEC acceptance criterion 7 (changing prod does not modify dev state)
 * structural rather than a convention someone has to remember.
 *
 * Everything below is either a composite call or a typed resource. No kustomize
 * overlay, no patch file, no raw YAML.
 */

import { HelmRepository } from "@intentius/chant-lexicon-k8s";
import { FluxAppFor, FluxGitSource } from "@intentius/chant-lexicon-k8s";

import {
  ACK_CHART_REGISTRY,
  AckController,
  FLUX_NAMESPACE,
  INFRA_NAMESPACE,
  PostgresInstance,
  ReaderIam,
  RegionCluster,
  SecureBucket,
  infraLabels,
  type SecretRef,
} from "../../composites/index.js";

const ENV = "dev";
const REGION = "us-east-1";
const ACK_REPOSITORY = "aws-controllers-k8s";

// ── Cluster ──────────────────────────────────────────────────────────────────
// SPEC: 2 nodes, t3.medium.

export const cluster = RegionCluster({
  name: "myapp-dev",
  env: ENV,
  region: REGION,
  availabilityZones: ["us-east-1a", "us-east-1b"],
  nodeCount: 2,
  instanceType: "t3.medium",
  publicEndpoint: true,
});

// ── Application assets bucket ────────────────────────────────────────────────
// SPEC dev: versioned + encrypted. Replication is the prod arm.

export const assets = SecureBucket({
  name: "myapp-assets-dev",
  env: ENV,
  region: REGION,
});

// ── Database ─────────────────────────────────────────────────────────────────
// SPEC dev: db.t3.micro, single AZ.

/**
 * Referenced provenance. The Secret is created out of band — nothing in this
 * repo holds the value, and nothing in the build output does either.
 */
const masterPassword: SecretRef = {
  name: "myapp-dev-db-master",
  namespace: INFRA_NAMESPACE,
  key: "password",
  scope: "created by the platform runbook before the DBInstance reconciles",
};

export const database = PostgresInstance({
  name: "myapp-dev-db",
  env: ENV,
  instanceClass: "db.t3.micro",
  databaseName: "appdb",
  masterUsername: "appuser",
  masterPassword,
  dbSubnetGroupName: "myapp-dev-subnets",
  multiAZ: false,
  vpcSecurityGroupIDs: ["sg-dev-database"],
});

// ── Service-account identity ─────────────────────────────────────────────────
// SPEC dev: programmatic access.

export const reader = ReaderIam({
  name: "myapp-dev",
  env: ENV,
  bucketName: "myapp-assets-dev",
  trust: { mode: "account", accountID: "123456789012" },
  programmaticAccess: true,
});

// ── Chart-delivered controllers ──────────────────────────────────────────────
// The ACK controllers that reconcile the custom resources above are themselves
// chart-delivered — declared as typed Flux objects, not applied by hand.

const ackLabels = infraLabels("ack", ENV);

export const ackCharts = new HelmRepository({
  metadata: {
    name: ACK_REPOSITORY,
    namespace: FLUX_NAMESPACE,
    labels: ackLabels,
  },
  spec: {
    type: "oci",
    url: ACK_CHART_REGISTRY,
    interval: "1h",
  },
});

export const s3Controller = AckController({
  service: "s3",
  env: ENV,
  region: REGION,
  chartVersion: "1.0.30",
  repositoryName: ackCharts.name,
});

export const rdsController = AckController({
  service: "rds",
  env: ENV,
  region: REGION,
  chartVersion: "1.4.14",
  repositoryName: ackCharts.name,
});

export const iamController = AckController({
  service: "iam",
  env: ENV,
  region: REGION,
  chartVersion: "1.3.16",
  repositoryName: ackCharts.name,
});

// ── Delivery ─────────────────────────────────────────────────────────────────
// One GitRepository source, one Kustomization per reconciled path — the
// lexicon's tested Flux composites, not hand-rolled ones.

export const source = FluxGitSource("myapp-infra", {
  url: "https://github.com/example/myapp-infra",
  branch: "main",
  interval: "1m",
});

export const infraApp = FluxAppFor("myapp-dev-infra", {
  source,
  path: "./dist/dev/infra",
  targetNamespace: INFRA_NAMESPACE,
  interval: "10m",
});

export const clusterApp = FluxAppFor("myapp-dev-clusters", {
  source,
  path: "./dist/dev/clusters",
  interval: "10m",
  dependsOn: ["myapp-dev-infra"],
});
