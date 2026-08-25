/**
 * Referenced-secret plumbing — the interim for chant's SOPS gap.
 *
 * ── Why this file exists ─────────────────────────────────────────────────────
 *
 * chant's secret-provenance vocabulary has four kinds as of `@intentius/chant`
 * 0.49.0 (this golden's current pin): `referenced`, `from-provider`,
 * `generated-once`, and `committed-encrypted` for SOPS-style ciphertext
 * committed in the repo. When this file was written, only the first three
 * were published; the knr-ops arm of this benchmark commits SOPS ciphertext,
 * this arm couldn't yet, so it used the closest kind chant did model —
 * `referenced`: the value exists out of band, a human or an external process
 * put it where consumers read it, and the estate records only that it
 * depends on it.
 *
 * ── Why it is a hand-rolled type and not `declareSecret` ─────────────────────
 *
 * `declareSecret({ name, provenance: "referenced", scope })` is the primitive
 * that turns that dependency into a first-class Declarable — collected by
 * discovery, listed by `chant list`, readable by lint, emitted by no
 * serializer. It was unpublished when this file was written (chant main
 * branch only, after 0.46.0); `@intentius/chant@0.49.0` now ships it,
 * including the `committed-encrypted` kind. So the discipline is kept
 * structurally here instead: a `SecretRef` carries a name, a namespace, and a
 * key, and there is no field on it that could carry material. Swapping this
 * file for real `declareSecret`/`describeSecret()` calls (and, separately,
 * for `committed-encrypted` provenance on the DB secret) is a scenario change
 * this registry re-pin deliberately leaves alone — see README, "Coverage
 * gaps" #1.
 *
 * The constitutional line is the same either way: no value, no ciphertext, no
 * hash of a value ever appears in this repo or in the build output.
 */

/** A pointer at a key inside a Kubernetes Secret that exists out of band. */
export interface SecretRef {
  /** Name of the Secret object. */
  name: string;
  /** Namespace the Secret lives in. */
  namespace: string;
  /** Key within the Secret's data. */
  key: string;
  /**
   * Free-form note about where the value comes from — the vault path, the
   * runbook, the human. This is the `scope` field of a `referenced` secret
   * declaration; it documents provenance, it is never the value.
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

/**
 * A human-readable provenance line for a referenced secret, for the README and
 * for `chant explain` output. The successor to this function is a
 * `declareSecret({ provenance: "referenced" })` call.
 */
export function describeSecret(ref: SecretRef): string {
  const where = ref.scope === undefined ? "out of band" : ref.scope;
  return `${ref.namespace}/${ref.name}[${ref.key}] — referenced, materialized ${where}`;
}
