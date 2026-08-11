import * as pulumi from "@pulumi/pulumi";
import * as aws from "@pulumi/aws";

// SEED REPO: Pulumi TypeScript with async misuse + wrong pulumi.output() wrapping
// Defect 1: async function used without .apply() — crashes at preview time
// Defect 2: pulumi.output() wrapping non-Output value causes type mismatch

const config = new pulumi.Config();
const env = config.get("env") || "dev";
const region = config.get("region") || "us-east-1";

// S3 Bucket
const bucket = new aws.s3.Bucket("app-bucket", {
    bucket: `myapp-assets-${env}`,
    versioning: { enabled: true },
    tags: { Environment: env, Project: "myapp" },
});

// DEFECT: async function used without proper Output handling
// This causes preview to crash with async/await misuse
async function getBucketUrl(arn: pulumi.Output<string>) {
    // Wrong: using await on Output instead of .apply()
    const resolved = await arn;  // DEFECT: crashes at runtime
    return `https://s3.${region}.amazonaws.com/${resolved}`;
}

const bucketUrl = getBucketUrl(bucket.arn);  // Returns Promise, not Output

// DEFECT: pulumi.output() wrapping a string literal (not an Output)
// This creates an unnecessary Output wrapper
const dbPassword = pulumi.output("plain-text-password");  // Should use config.requireSecret()

// RDS Instance
const db = new aws.rds.Instance("app-db", {
    instanceClass: "db.t3.medium",
    engine: "postgres",
    engineVersion: "16.1",
    allocatedStorage: 20,
    dbName: "appdb",
    username: "app-user",
    password: dbPassword,
    skipFinalSnapshot: true,
    deletionProtection: false,  // Should be true for prod
});

// Output
export const bucketEndpoint = bucketUrl;  // Exporting a Promise, not an Output
export const dbEndpoint = db.endpoint;
