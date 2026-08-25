# vendor/

Empty on purpose. This golden used to pin `@intentius/chant` and
`@intentius/chant-lexicon-k8s` to tarballs built off chant branch
`bench/lexicon-capi-ack`, because the CAPI/CAPA/ACK typed kinds and the
`secret-provenance` module they depend on had not shipped to the registry
yet.

INTENTIUS/chant released v0.49.0 with that work merged, so `../package.json`
now resolves both packages as plain `^0.49.0` registry dependencies. There is
nothing left to vendor.

If a future golden change needs a capability the published release doesn't
have yet, that is what this directory is for again — see git history for the
tarball-vendoring pattern this replaced.
