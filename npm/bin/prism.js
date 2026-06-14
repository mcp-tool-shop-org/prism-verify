#!/usr/bin/env node
"use strict";

// Thin npm wrapper for the prism CLI. Pure JSON config — @mcptoolshop/npm-launcher derives the
// release-asset names from convention, downloads the platform binary from the prism-verify
// GitHub Release, verifies its SHA256 against checksums-<version>.txt, caches it, and runs it
// with full arg passthrough.
//
// version + tag are derived from package.json at runtime so the wrapper can NEVER ship a stale
// binary pin: bumping the published npm version automatically targets the matching GitHub Release
// (e.g. for 1.3.0 → binary prism-1.3.0-linux-x64, checksums checksums-1.3.0.txt).
const pkgVersion = require("../package.json").version;
process.env.MCPTOOLSHOP_LAUNCH_CONFIG = JSON.stringify({
  toolName: "prism",
  owner: "mcp-tool-shop-org",
  repo: "prism-verify",
  version: pkgVersion,
  tag: "v" + pkgVersion,
});

require("@mcptoolshop/npm-launcher/bin/mcptoolshop-launch.js");
