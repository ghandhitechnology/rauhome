import { randomUUID } from "node:crypto";
import { createServer } from "node:http";
import { FAUX_SCENARIOS } from "./models.mjs";
import { ACTIVE_STATES, DEFAULTS, PiRun, withDefaults } from "./run.mjs";

const HOST = process.env.PI_SIDECAR_HOST ?? "127.0.0.1";
const PORT = Number(process.env.PI_SIDECAR_PORT ?? 8791);
const MAX_RUNS = 40;

const runs = new Map();

function trimRuns() {
	const finished = [...runs.values()]
		.filter((run) => !ACTIVE_STATES.has(run.state))
		.sort((a, b) => a.updated - b.updated);
	while (runs.size > MAX_RUNS && finished.length > 0) runs.delete(finished.shift().id);
}

function send(res, status, body) {
	const payload = JSON.stringify(body);
	res.writeHead(status, { "content-type": "application/json", "content-length": Buffer.byteLength(payload) });
	res.end(payload);
}

async function readJson(req) {
	const chunks = [];
	for await (const chunk of req) chunks.push(chunk);
	if (chunks.length === 0) return {};
	return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function streamEvents(req, res, run) {
	res.writeHead(200, {
		"content-type": "text/event-stream",
		"cache-control": "no-cache",
		connection: "keep-alive",
	});
	const unsubscribe = run.subscribe((event) => {
		// A client can disconnect between two events, and `close` fires late enough
		// that a write can still be attempted afterwards. Writing to an ended
		// response throws out of the run's emit loop, which would take down every
		// other run in this process along with it.
		if (res.writableEnded) return;
		res.write(`data: ${JSON.stringify(event)}\n\n`);
		if (event.type === "close") res.end();
	});
	// A run that finished before the client attached replays from history and
	// gets no further events, so close the stream rather than hang it open.
	if (!ACTIVE_STATES.has(run.state)) {
		res.write(`data: ${JSON.stringify({ type: "close", ts: Date.now() })}\n\n`);
		res.end();
	}
	req.on("close", unsubscribe);
}

const server = createServer(async (req, res) => {
	const url = new URL(req.url, `http://${req.headers.host}`);
	const path = url.pathname;

	try {
		if (req.method === "GET" && path === "/health") {
			return send(res, 200, {
				ok: true,
				service: "rau-pi-sidecar",
				node: process.version,
				faux_scenarios: FAUX_SCENARIOS,
				defaults: DEFAULTS,
				runs: runs.size,
			});
		}

		if (req.method === "GET" && path === "/runs") {
			return send(res, 200, { runs: [...runs.values()].map((run) => run.snapshot()) });
		}

		if (req.method === "POST" && path === "/runs") {
			const options = withDefaults(await readJson(req));
			const run = new PiRun({ ...options, id: randomUUID() });
			runs.set(run.id, run);
			trimRuns();
			// Detached on purpose: the response carries the id, and the caller
			// follows the run over /events.
			run.start();
			return send(res, 201, run.snapshot());
		}

		const match = /^\/runs\/([^/]+)(\/[a-z]+)?$/.exec(path);
		if (match) {
			const run = runs.get(match[1]);
			if (!run) return send(res, 404, { error: "unknown run" });
			const action = match[2];

			if (req.method === "GET" && !action) return send(res, 200, run.snapshot());
			if (req.method === "GET" && action === "/events") return streamEvents(req, res, run);
			if (req.method === "POST" && action === "/cancel") {
				const cancelled = await run.cancel();
				return send(res, 200, { cancelled, ...run.snapshot() });
			}
			if (req.method === "POST" && action === "/confirm") {
				const body = await readJson(req);
				const accepted = run.confirm(body.confirm_id, Boolean(body.approved));
				return send(res, 200, { accepted, ...run.snapshot() });
			}
		}

		return send(res, 404, { error: "not found" });
	} catch (error) {
		return send(res, 400, { error: error instanceof Error ? error.message : String(error) });
	}
});

server.listen(PORT, HOST, () => {
	process.stdout.write(`rau-pi-sidecar listening on http://${HOST}:${PORT}\n`);
});
