// Send one built stage file (e.g. prompts/stage-fast-video.json) to Google Flow through flow-mcp and wait for it.
// Use this when the agent has no flow_* MCP tools (e.g. a script run) or to time a batch exactly.
//
//   node run_stage.mjs <stage.json> [--flow-mcp <path to flow-mcp folder>] [--project-url <flow project url>] [--only 2,3] [--out run.json]
//   (--only takes storyboard scene ids; the result is also saved as last-run.json next to the stage file)
//
// Prints one progress line per 20 s and a final JSON block: per scene status, credits, files, wall time.
// It spends the credits the stage asks for (each scene has its own max_credits cap). Exit 0 = every scene done.
import { readFileSync, existsSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const args = process.argv.slice(2);
const opt = (k) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : undefined; };
const stageFile = args.find((a) => a.endsWith(".json"));
if (!stageFile) { console.error("usage: node run_stage.mjs <stage.json> [--flow-mcp DIR] [--project-url URL] [--only 1,3]"); process.exit(2); }
const candidates = [opt("--flow-mcp"), process.env.FLOW_MCP_DIR, join(homedir(), "flow-mcp"), resolve("flow-mcp"), resolve("..", "flow-mcp")].filter(Boolean);
const fm = candidates.find((d) => existsSync(join(d, "dist", "core.js")));
if (!fm) { console.error("flow-mcp not found (pass --flow-mcp or set FLOW_MCP_DIR)"); process.exit(2); }
const { LocalCore } = await import(pathToFileURL(join(fm, "dist", "core.js")).href);
const { getFlowPage } = await import(pathToFileURL(join(fm, "dist", "chrome.js")).href);

const stage = JSON.parse(readFileSync(stageFile, "utf8"));
let scenes = stage.scenes;
const only = opt("--only");
// --only takes storyboard scene ids (the builder writes scene_id); a stage without ids falls back to positions.
if (only) { const keep = new Set(only.split(",").map(Number)); scenes = scenes.filter((s, i) => keep.has(Number(s.scene_id ?? i + 1))); }
if (!scenes.length) { console.error(`no scene in ${stageFile} matches --only ${only}`); process.exit(2); }
const t0 = Date.now();
const secs = () => ((Date.now() - t0) / 1000).toFixed(0);

const url = opt("--project-url");
if (url) { const page = await getFlowPage(); if (!page.url().startsWith(url)) { await page.goto(url); await page.waitForTimeout(8000); } }
const core = new LocalCore();
const st = await core.status({ detailed: true });
if (!st.flow.signedIn || !st.flow.inProject) { console.log(JSON.stringify({ error: st.flow.hint })); process.exit(2); }
console.log(`[${secs()}s] Flow ok, credits ${st.flow.credits_remaining}; submitting ${scenes.length} scene(s)`);
const res = await core.generate({ project: stage.project, scenes });
const ids = res.jobs.map((j) => j.id);
let last = 0, w;
for (;;) {
  w = await core.wait({ job_ids: ids, timeout_seconds: 20 });
  if (Date.now() - last > 19_000) { last = Date.now(); console.log(`[${secs()}s] ${w.jobs.map((j) => j.status + (j.progress ? `(${j.progress})` : "")).join(" | ")}`); }
  if (w.finished) break;
}
const out = { project: stage.project, output_dir: res.output_dir, wall_seconds: Number(secs()),
  scenes: w.jobs.map((j, i) => ({ scene_id: scenes[i]?.scene_id, id: j.id, status: j.status, credits: j.credits, files: j.files, error: j.error })) };
// Saved next to the stage file so fast_review.py can map scene ids to clips.
const outFile = opt("--out") ?? join(dirname(resolve(stageFile)), "last-run.json");
writeFileSync(outFile, JSON.stringify(out, null, 2));
console.log(JSON.stringify(out, null, 2));
console.log(`saved ${outFile}`);
process.exit(w.jobs.every((j) => j.status === "done") ? 0 : 1);
