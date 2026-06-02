---
title: Getting started
description: Install prism, configure a verifier + signing key, and run your first verification.
sidebar:
  order: 1
---

## Install

prism ships to PyPI (the full-featured Python package) and npm (a zero-Python launcher).

```bash
# Python (recommended — full features, all providers):
uv tool install prism-verify        # or: pipx install prism-verify

# Zero Python — downloads + SHA256-verifies a prebuilt binary:
npx @mcptoolshop/prism-verify --help

# As a library, with extras:
pip install "prism-verify[all]"     # [anthropic] [openai] [google] [mcp] [http] [all]
```

## Configure a verifier

prism verifies with a model family **different** from the caller's, so you need at least one
alternate-family provider configured. The always-available option is local **Ollama**; hosted
providers (Anthropic / OpenAI / Google) are used when their API key is set.

```bash
export ANTHROPIC_API_KEY="sk-ant-..."   # an alt-family verifier for an OpenAI-family caller
# local Ollama needs no key — pin a non-thinking model, e.g. mistral-small:24b
```

## Configure a signing key

Every verification writes a signed receipt, so prism needs a signing key — it **refuses to start**
otherwise (it will not silently sign with a public dev key). v0.4 defaults to **Ed25519**:

```bash
prism keygen --out ~/.prism/signing_key.pem
export PRISM_SIGNING_KEY=~/.prism/signing_key.pem
# or, for local play only:
export PRISM_DEV=1                       # a built-in dev Ed25519 key — INSECURE, local only
# legacy HMAC is still supported:
export PRISM_SIGNING_SECRET="$(openssl rand -hex 32)"
```

## Your first verification

```bash
prism verify \
  --artifact @myfile.py \
  --intent "Sort a list in O(n log n)" \
  --caller-family openai \
  --provider ollama
```

prism prints a JSON result with the `verdict`, per-lens findings, the pairwise correlation
matrix, and a signed `receipt`.

## Gate on the verdict in a shell

`--gate` maps the verdict to an exit code so CI can branch on it (the default, without `--gate`,
stays exit `0` on any successful verification):

```bash
prism verify -a @code.py -i "..." --caller-family openai --gate
# exit 0 accept · 10 revise · 20 refuse · 30 escalate
```

Next: stand it up as an [HTTP service](../http-service/), or learn how
[receipts](../receipts/) make a verdict independently verifiable.
