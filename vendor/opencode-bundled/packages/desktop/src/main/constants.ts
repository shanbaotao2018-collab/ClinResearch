import { app } from "electron"

type Channel = "dev" | "beta" | "prod"
const raw = import.meta.env.OPENCODE_CHANNEL
export const CHANNEL: Channel = raw === "dev" || raw === "beta" || raw === "prod" ? raw : "dev"

// This branded distribution is built and released locally, not through the
// upstream OpenCode update channel. Keeping it disabled preserves the custom
// identity and avoids replacing the app with an upstream binary.
export const UPDATER_ENABLED = false
