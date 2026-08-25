// GOLDEN: app-bucket and app-db moved into a ComponentResource, with
// aliases pointing back at their un-parented (seed) logical names so
// Pulumi treats this as an in-place adoption, not a replacement.

import * as pulumi from "@pulumi/pulumi";
import * as aws from "@pulumi/aws";

const config = new pulumi.Config();
const env = config.get("env") || "dev";

export class AppStack extends pulumi.ComponentResource {
    public readonly bucket: aws.s3.Bucket;
    public readonly db: aws.rds.Instance;

    constructor(name: string, opts?: pulumi.ComponentResourceOptions) {
        super("myapp:index:AppStack", name, {}, opts);

        this.bucket = new aws.s3.Bucket("app-bucket", {
            bucket: `myapp-assets-${env}`,
            versioning: { enabled: true },
            tags: { Environment: env },
        }, { parent: this, aliases: [{ name: "app-bucket" }] });

        this.db = new aws.rds.Instance("app-db", {
            instanceClass: "db.t3.medium",
            engine: "postgres",
            engineVersion: "16.1",
            allocatedStorage: 20,
            dbName: "appdb",
            username: "app-user",
            password: config.requireSecret("dbPassword"),
            skipFinalSnapshot: true,
        }, { parent: this, aliases: [{ name: "app-db" }] });

        this.registerOutputs({
            bucketArn: this.bucket.arn,
            dbEndpoint: this.db.endpoint,
        });
    }
}

const stack = new AppStack("app-stack");

export const bucketArn = stack.bucket.arn;
export const dbEndpoint = stack.db.endpoint;
