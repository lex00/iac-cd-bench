/**
 * Secret plumbing: the ACK/Flux-facing pointer shape, plus the real
 * provenance declaration for the one secret this golden commits ciphertext
 * for.
 *
 * ── Two separate concerns ────────────────────────────────────────────────────
 *
 * `SecretRef` / `secretRef()` / `fluxSecretRef()` answer "where does the
 * *consumer* point": ACK's `SecretKeyReference` wants `{ name, namespace,
 * key }`, Flux's `secretRef` wants `{ name }`. That shape is the same no
 * matter how the Secret got there, so it is unchanged by the rest of this
 * file — `PostgresInstance` still calls `secretRef(props.masterPassword)`.
 *
 * `describeSecret()` answers a different question: "where did the value come
 * from, and can chant verify that claim." That used to be a hand-rolled
 * string formatter — a structural stand-in for `declareSecret()`, which
 * landed on chant's main branch after the published `@intentius/chant@0.46.0`
 * this golden pins (iac-cd-bench#6/#16/#32). It is vendored now (see
 * ../../vendor/README.md), so `describeSecret()` makes the real call: a
 * `declareSecret({ provenance: "committed-encrypted", file })` for
 * `myapp-dev-db-master`, the SOPS ciphertext committed at
 * `secrets/db-credentials.dev.sops.yaml`. Its return value is a Declarable —
 * export it from a build root and discovery, `chant list`, and the k8s
 * lexicon's WK8503/WK8504 post-synth checks all see it. No serializer emits
 * it as a document; the k8s lexicon's `buildRoots()` hook reads the ciphertext
 * bytes at build time and routes them to `SerializerResult.files` as a
 * verbatim sidecar (see README, "Secrets: committed-encrypted SOPS
 * ciphertext").
 *
 * The constitutional line is unchanged either way: no value, no ciphertext,
 * no hash of a value ever appears in this file, and `declareSecret` itself
 * refuses any input field shaped like material (`value`, `data`,
 * `stringData`, `plaintext`, `ciphertext`, …) at both the type level and at
 * runtime.
 */

import { declareSecret, type CommittedEncryptedSecretDeclaration } from "@intentius/chant/secret-provenance";

/** A pointer at a key inside a Kubernetes Secret. Says nothing about how the
 * Secret was produced — referenced out of band, or committed as ciphertext
 * and decrypted by Flux — only where a consumer finds it once it exists. */
export interface SecretRef {
  /** Name of the Secret object. */
  name: string;
  /** Namespace the Secret lives in. */
  namespace: string;
  /** Key within the Secret's data. */
  key: string;
  /**
   * Free-form note about where the value comes from — the vault path, the
   * runbook, the human. Documentation only; still never the value. Only
   * meaningful for a Secret whose provenance is `referenced` — see
   * `describeSecret()` for the committed-encrypted case, which declares
   * provenance separately rather than folding it into this note.
   */
  scope?: string;
}

/** The `{ name, namespace, key }` shape ACK's `SecretKeyReference` expects. */
export function secretRef(ref: SecretRef): { name: string; namespace: string; key: string } {
  return { name: ref.name, namespace: ref.namespace, key: ref.key };
}

/** The `{ name }` shape Flux's `valuesFrom`/`secretRef` fields expect. */
export function fluxSecretRef(ref: SecretRef): { name: string } {
  return { name: ref.name };
}

/** Points `describeSecret()` at the committed ciphertext for a Secret. */
export interface CommittedSecretRef {
  /** Name of the Secret object — must equal `metadata.name` in `file`. */
  name: string;
  /**
   * Repo-relative path to the committed SOPS ciphertext (`.yaml`/`.yml`
   * only — chant's CLI writer round-trips other extensions through
   * `JSON.parse` and would break the byte-for-byte emission guarantee).
   */
  file: string;
  /** The decrypted Secret's declared key-set — names only, never values. */
  keys?: readonly string[];
}

/**
 * Declares a Secret's provenance as committed-encrypted SOPS ciphertext. The
 * returned Declarable is what discovery, `chant list`, and the k8s lexicon's
 * WK8503 (producer set) / WK8504 (ciphertext-shape check) read — export it
 * from a build root alongside the `SecretRef` consumers use to point at the
 * same name.
 */
export function describeSecret(ref: CommittedSecretRef): CommittedEncryptedSecretDeclaration {
  return declareSecret({
    name: ref.name,
    provenance: "committed-encrypted",
    file: ref.file,
    keys: ref.keys,
  });
}
