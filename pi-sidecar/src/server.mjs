import { randomUUID, timingSafeEqual } from "node:crypto";
import { createServer } from "node:http";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { FAUX_SCENARIOS } from "./models.mjs";
import { ACTIVE_STATES, DEFAULTS, PiRun, PROJECT_ROOT, withDefaults } from "./run.mjs";

const HOST = process.env.PI_SIDECAR_HOST ?? "127.0.0.1";
const parsedPort = Number(process.env.PI_SIDECAR_PORT ?? 8791);
const PORT = Number.isInteger(parsedPort) && parsedPort >= 0 && parsedPort <= 65_535 ? parsedPort : 8791;
const MAX_RUNS = 40;
const MAX_ACTIVE_RUNS = 8;
const MAX_BODY_BYTES = 1024 * 1024;
const SSE_HEARTBEAT_MS = 15_000;

class HttpError extends Error {
	constructor(status, message) {
		super(message);
		this.status = status;
	}
}

function send(res, status, body) {
	if (res.headersSent || res.writableEnded || res.destroyed) return;
	const payload = JSON.stringify(body);
	res.writeHead(status, {
		"content-type": "application/json",
		"content-length": Buffer.byteLength(payload),
		"cache-control": "no-store",
		"x-content-type-options": "nosniff",
	});
	res.end(payload);
}

function authorized(req, token) {
	if (!token) return true;
	const match = /^Bearer\s+([^\s]+)$/i.exec(String(req.headers.authorization ?? ""));
	if (!match) return false;
	const supplied = match[1];
	const expectedBytes = Buffer.from(token);
	const suppliedBytes = Buffer.from(supplied);
	return (
		expectedBytes.length === suppliedBytes.length &&
		timingSafeEqual(expectedBytes, suppliedBytes)
	);
}

async function readJson(req, maxBodyBytes) {
	const contentType = String(req.headers["content-type"] ?? "")
		.split(";", 1)[0]
		.trim()
		.toLowerCase();
	if (contentType !== "application/json") {
		throw new HttpError(415, "content-type must be application/json");
	}
	const declared = Number(req.headers["content-length"]);
	if (Number.isFinite(declared) && declared > maxBodyBytes) {
		throw new HttpError(413, `request body exceeds ${maxBodyBytes} bytes`);
	}
	const chunks = [];
	let size = 0;
	for await (const chunk of req) {
		size += chunk.length;
		if (size > maxBodyBytes) throw new HttpError(413, `request body exceeds ${maxBodyBytes} bytes`);
		chunks.push(chunk);
	}
	if (chunks.length === 0) return {};
	try {
		const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
		if (!body || typeof body !== "object" || Array.isArray(body)) {
			throw new HttpError(400, "request body must be a JSON object");
		}
		return body;
	} catch (error) {
		if (error instanceof HttpError) throw error;
		throw new HttpError(400, "malformed JSON request body");
	}
}

function sequenceCursor(req, url) {
	const raw = url.searchParams.get("after") ?? req.headers["last-event-id"] ?? "0";
	const parsed = Number(raw);
	return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : 0;
}

function streamEvents(req, res, run, afterSeq) {
	res.writeHead(200, {
		"content-type": "text/event-stream",
		"cache-control": "no-cache, no-store",
		connection: "keep-alive",
		"x-accel-buffering": "no",
		"x-content-type-options": "nosniff",
	});

	let closed = false;
	let unsubscribe = () => {};
	const cleanup = () => {
		if (closed) return;
		closed = true;
		clearInterval(heartbeat);
		unsubscribe();
	};
	const write = (event) => {
		if (closed || res.writableEnded || res.destroyed) return;
		try {
			res.write(`id: ${event.seq ?? ""}\ndata: ${JSON.stringify(event)}\n\n`);
			if (event.type === "close") {
				cleanup();
				res.end();
			}
		} catch {
			cleanup();
			res.destroy();
		}
	};
	const heartbeat = setInterval(() => {
		if (closed || res.writableEnded || res.destroyed) return cleanup();
		try {
			res.write(`: keepalive ${Date.now()}\n\n`);
		} catch {
			cleanup();
		}
	}, SSE_HEARTBEAT_MS);
	heartbeat.unref();

	unsubscribe = run.subscribe(write, afterSeq);
	// A run that finished before the client attached replays its terminal
	// result and has no future close event, so close this particular stream.
	if (!ACTIVE_STATES.has(run.state) && !closed) {
		write({ seq: run.seq + 1, type: "close", ts: Date.now() });
	}
	req.once("close", cleanup);
	res.once("close", cleanup);
	res.once("error", cleanup);
}

export function createSidecarServer({
	root = PROJECT_ROOT,
	maxRuns = MAX_RUNS,
	maxActiveRuns = MAX_ACTIVE_RUNS,
	maxBodyBytes = MAX_BODY_BYTES,
	token = process.env.PI_SIDECAR_TOKEN ?? "",
} = {}) {
	const runs = new Map();

	function trimRuns() {
		const finished = [...runs.values()]
			.filter((run) => run.closed)
			.sort((a, b) => a.updated - b.updated);
		while (runs.size >= maxRuns && finished.length > 0) runs.delete(finished.shift().id);
	}

	const server = createServer(async (req, res) => {
		if (!authorized(req, token)) {
			return send(res, 401, { error: "unauthorized" });
		}
		// The Host header is attacker-controlled and only a base is needed to
		// parse a relative request target, so never feed it into URL().
		let url;
		try {
			url = new URL(req.url ?? "/", "http://127.0.0.1");
		} catch {
			return send(res, 400, { error: "invalid request target" });
		}
		const path = url.pathname;

		try {
			if (req.method === "GET" && path === "/health") {
				return send(res, 200, {
					ok: true,
					service: "rau-pi-sidecar",
					node: process.version,
					faux_scenarios: FAUX_SCENARIOS,
					defaults: DEFAULTS,
					root,
					runs: runs.size,
					active_runs: [...runs.values()].filter((run) => !run.closed).length,
				});
			}

			if (req.method === "GET" && path === "/runs") {
				return send(res, 200, { runs: [...runs.values()].map((run) => run.snapshot()) });
			}

			if (req.method === "POST" && path === "/runs") {
				const active = [...runs.values()].filter((run) => !run.closed).length;
				if (active >= maxActiveRuns) throw new HttpError(429, `active run limit of ${maxActiveRuns} reached`);
				trimRuns();
				if (runs.size >= maxRuns) throw new HttpError(429, `run registry limit of ${maxRuns} reached`);
				const options = withDefaults(await readJson(req, maxBodyBytes), root);
				const run = new PiRun({ ...options, id: randomUUID() });
				runs.set(run.id, run);
				// Detached on purpose: the response carries the id, and the
				// caller follows the run over /events.
				void run.start();
				return send(res, 201, run.snapshot());
			}

			const match = /^\/runs\/([0-9a-f-]+)(\/[a-z]+)?$/i.exec(path);
			if (match) {
				const run = runs.get(match[1]);
				if (!run) return send(res, 404, { error: "unknown run" });
				const action = match[2];

				if (req.method === "GET" && !action) return send(res, 200, run.snapshot());
				if (req.method === "GET" && action === "/events") {
					return streamEvents(req, res, run, sequenceCursor(req, url));
				}
				if (req.method === "POST" && action === "/cancel") {
					await readJson(req, maxBodyBytes);
					const cancelled = await run.cancel();
					return send(res, 200, { cancelled, ...run.snapshot() });
				}
				if (req.method === "POST" && action === "/confirm") {
					const body = await readJson(req, maxBodyBytes);
					if (typeof body.approved !== "boolean") throw new HttpError(400, "approved must be a boolean");
					if (body.confirm_id !== undefined && typeof body.confirm_id !== "string") {
						throw new HttpError(400, "confirm_id must be a string");
					}
					const accepted = run.confirm(body.confirm_id, body.approved);
					return send(res, 200, { accepted, ...run.snapshot() });
				}
			}

			return send(res, 404, { error: "not found" });
		} catch (error) {
			const status = error instanceof HttpError ? error.status : 400;
			return send(res, status, { error: error instanceof Error ? error.message : String(error) });
		}
	});

	server.runs = runs;
	server.cancelRuns = async () => {
		await Promise.allSettled(
			[...runs.values()].map(async (run) => {
				await run.cancel();
				await run.completion;
			}),
		);
	};
	return server;
}

const isMain = process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url;
if (isMain) {
	const loopback = new Set(["127.0.0.1", "::1", "localhost"]);
	if (!loopback.has(HOST) && (process.env.PI_SIDECAR_TOKEN ?? "").length < 32) {
		throw new Error(
			"PI_SIDECAR_TOKEN must contain at least 32 characters when binding beyond loopback",
		);
	}
	const server = createSidecarServer();
	server.listen(PORT, HOST, () => {
		const address = server.address();
		const port = typeof address === "object" && address ? address.port : PORT;
		process.stdout.write(`rau-pi-sidecar listening on http://${HOST}:${port}\n`);
	});

	let stopping = false;
	const shutdown = () => {
		if (stopping) return;
		stopping = true;
		void server.cancelRuns().finally(() => {
			server.close(() => process.exit(0));
		});
		setTimeout(() => process.exit(1), 10_000).unref();
	};
	process.once("SIGINT", shutdown);
	process.once("SIGTERM", shutdown);
}
