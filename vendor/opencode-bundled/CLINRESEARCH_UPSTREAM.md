# ClinResearch OpenCode Source

This directory contains the source code used to build the branded
ClinResearch desktop client. It is based on OpenCode commit:

`012c2f57f976489d88bd4598a056b4bdcdd428ee`

Upstream project: <https://github.com/anomalyco/opencode>

OpenCode is licensed under the MIT License. The upstream license is preserved
in `LICENSE`. ClinResearch-specific changes include application branding,
the four-agent welcome experience, Chinese agent display names, the bundled
local literature connector, and release validation.

Generated dependencies and release outputs are intentionally excluded. Run
`bun install --frozen-lockfile` to restore the exact dependency graph recorded
in `bun.lock`.
