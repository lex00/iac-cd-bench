// SEED REPO: flat Pulumi program (no ComponentResource wrapper). Migrate
// this to a ComponentResource without triggering replacement of app-bucket
// or app-db.

import * as pulumi from "@pulumi/pulumi";
import * as aws from "@pulumi/aws";

const config = new pulumi.Config();
const env = config.get("env") || "dev";

export const bucket = new aws.s3.Bucket("app-bucket", {
    bucket: `myapp-assets-${env}`,
    versioning: { enabled: true },
    tags: { Environment: env },
});

export const db = new aws.rds.Instance("app-db", {
    instanceClass: "db.t3.medium",
    engine: "postgres",
    engineVersion: "16.1",
    allocatedStorage: 20,
    dbName: "appdb",
    username: "app-user",
    password: config.requireSecret("dbPassword"),
    skipFinalSnapshot: true,
});

export const bucketArn = bucket.arn;
export const dbEndpoint = db.endpoint;
