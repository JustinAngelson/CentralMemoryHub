# Post-cutover backlog

- After the search compatibility hotfix merges, merge `main` back into `v2`
  if that development branch is retained, or formally retire it. Do not recreate
  a retired branch merely to synchronize it.
- C3 credential migration remains blocked until the search hotfix is live and
  post-publish verification passes.

## Search hotfix release checks

After Owner review, merge, and a separate explicit publish go:

1. Realign to the reviewed `main` commit and verify the only port mapping is
   `5000 → 80` before publishing.
2. Run `v2/check_production.py` against the live origin.
3. Mint one temporary credential through native administration. Using the
   authenticated live MCP transport, call `cmh_search_memory` and require a
   successful result with `structuredContent is None` and nonempty result text.
   Do not print memory content or credentials.
4. Revoke the temporary credential in a `finally` block, including on failure,
   and verify it is inactive. Verify the audit chain.
5. Report the results before starting C3.
