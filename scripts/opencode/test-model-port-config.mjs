import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const configUrl = new URL("../../opencode.json", import.meta.url);
const config = JSON.parse(await readFile(configUrl, "utf8"));
const options = config.provider?.["model-port"]?.options;

assert.equal(options?.timeout, 90_000, "model requests must fail visibly within 90 seconds");
assert.equal(options?.chunkTimeout, 90_000, "stalled model streams must fail visibly within 90 seconds");
assert.equal(options?.apiKey, "{env:MODEL_PORT_API_KEY}", "the API key must remain environment-supplied");

console.log("Model Port timeout configuration is safe for interactive agent runs.");
