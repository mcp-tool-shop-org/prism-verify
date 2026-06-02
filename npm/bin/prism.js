#!/usr/bin/env node
"use strict";

// Thin npm wrapper for the prism CLI. Pure JSON config — @mcptoolshop/npm-launcher derives the
// release-asset names from convention, downloads the platform binary from the prism-verify
// GitHub Release, verifies its SHA256 against checksums-<version>.txt, caches it, and runs it
// with full arg passthrough.
//   binary:    prism-0.4.0-linux-x64
//   checksums: checksums-0.4.0.txt
process.env.MCPTOOLSHOP_LAUNCH_CONFIG = JSON.stringify({
  toolName: "prism",
  owner: "mcp-tool-shop-org",
  repo: "prism-verify",
  version: "0.4.0",
  tag: "v0.4.0",
});

require("@mcptoolshop/npm-launcher/bin/mcptoolshop-launch.js");
