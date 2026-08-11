import * as pulumi from "@pulumi/pulumi";
import { S3BucketComponent } from "./components/bucket";
import { RDSComponent } from "./components/rds";
import { IAMComponent } from "./components/iam";

// Stack configuration
const config = new pulumi.Config();
const env = config.require("app:env");
const region = config.require("aws:region");
const instanceClass = config.require("app:instanceClass");
const instanceCount = config.requireNumber("app:instanceCount");
const dbPassword = config.requireSecret("app:dbPassword");
const dbUser = config.require("app:dbUser");
const dbName = config.require("app:dbName");
const bucketName = config.require("app:bucketName");

// Export configuration
export const environment = env;
export const region = region;

// Infrastructure components
const bucket = new S3BucketComponent(bucketName, {
  versioning: true,
  encryption: true,
  replicationTarget: config.get("app:replicationTargetBucket"),
});

const db = new RDSComponent(`${bucketName}-db`, {
  instanceClass,
  dbUser,
  dbName,
  dbPassword,
  multiAz: env === "prod",
  deletionProtection: true,
  backupRetention: 7,
  publiclyAccessible: false,
  storageEncrypted: true,
});

const iam = new IAMComponent(`${bucketName}-iam`, {
  environment: env,
  bucketArn: bucket.arn,
  isProd: env === "prod",
});

// Export outputs
export const bucketArn = bucket.arn;
export const dbEndpoint = db.endpoint;
export const dbPassword = db.password;
export const iamUserName = iam.userName;
export const iamAccessKeyId = iam.accessKeyId;
export const iamRoleArn = iam.roleArn;