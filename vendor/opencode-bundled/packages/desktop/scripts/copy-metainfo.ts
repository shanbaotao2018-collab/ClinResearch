import { resolveChannel } from "./utils"

const arg = process.argv[2]
const channel = arg === "dev" || arg === "beta" || arg === "prod" ? arg : resolveChannel()

const appId = channel === "prod" ? "com.clinresearch.workbench" : `ai.opencode.desktop.${channel}`
const productName =
  channel === "prod" ? "临床科研智能体工作台" : `OpenCode ${channel.charAt(0).toUpperCase() + channel.slice(1)}`
const summary =
  channel === "prod"
    ? "面向临床科研的研究设计、文献综述、证据分析与科研写作智能体工作台"
    : `Open source AI coding agent (${channel})`

const xml = `<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>${appId}</id>

  <metadata_license>CC0-1.0</metadata_license>
  <project_license>MIT</project_license>

  <name>${productName}</name>
  <summary>${summary}</summary>

  <developer id="com.clinresearch">
    <name>ClinResearch</name>
  </developer>

  <description>
    <p>
      ClinResearch is a traceable medical research agent workbench based on OpenCode.
    </p>
  </description>

  <launchable type="desktop-id">${appId}.desktop</launchable>

  <content_rating type="oars-1.1" />

  <url type="bugtracker">https://github.com/shanbaotao2018-collab/ClinResearch/issues</url>
  <url type="homepage">https://github.com/shanbaotao2018-collab/ClinResearch</url>
  <url type="vcs-browser">https://github.com/shanbaotao2018-collab/ClinResearch</url>
</component>
`

await Bun.write(`resources/${appId}.metainfo.xml`, xml)
console.log(`Generated metainfo for ${channel} at resources/${appId}.metainfo.xml`)
