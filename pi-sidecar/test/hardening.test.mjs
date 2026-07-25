import assert from "node:assert/strict";
import { access, mkdir, mkdtemp, rm, symlink } from "node:fs/promises";
import { dirname, join } from "node:path";
import { once } from "node:events";
import test from "node:test";
import { getBuiltinModels, getBuiltinProviders } from "@earendil-works/pi-ai/providers/all";
import { resolveModel } from "../src/models.mjs";
import {
	ConfinedExecutionEnv,
	PiRun,
	PROJECT_ROOT,
	withDefaults,
} from "../src/run.mjs";
import { createSidecarServer } from "../src/server.mjs";

function options(body = {}) {
	return withDefaults(
		{
			goal: "test goal",
			tools: [],
			confirm_tools: [],
			faux_scenario: "text",
			run_timeout_ms: 5_000,
			...body,
		},
		PROJECT_ROOT,
	);
}

test("request options reject malformed values and cwd escapes", () => {
	assert.throws(() => withDefaults(null), /JSON object/);
	assert.throws(() => withDefaults({ goal: "x", tools: "bash" }), /tools must be an array/);
	assert.throws(
		() => withDefaults({ goal: "x", confirm_timeout_ms: Number.NaN }),
		/confirm_timeout_ms/,
	);
	assert.throws(() => withDefaults({ goal: "x", max_turns: 0 }), /max_turns/);
	assert.throws(() => withDefaults({ goal: "x", cwd: "/tmp" }), /escapes configured root/);
	assert.throws(() => withDefaults({ goal: "x", provider: "../../evil" }), /provider/);
	const gated = withDefaults({ goal: "x", tools: ["bash"], confirm_tools: [] });
	assert.deepEqual(gated.confirmTools, ["bash"], "callers cannot disable mandatory confirmation");
});

test("every builtin provider factory can be selected", async () => {
	for (const provider of getBuiltinProviders()) {
		const model = getBuiltinModels(provider)[0]?.id;
		assert.ok(model, `${provider} has no catalog model`);
		await assert.doesNotReject(resolveModel({ provider, model }));
	}
});

test("in-memory skill bodies survive the Python-to-pi bridge", () => {
	const run = new PiRun({
		...options({
			skills: [
				{
					name: "audit",
					description: "Audit carefully",
					content: "CHECK_UNIQUE_SECURITY_INVARIANT",
					filePath: "",
				},
			],
		}),
		id: "skill-test",
	});
	assert.match(
		run.buildSystemPrompt({ skills: run.options.skills }),
		/CHECK_UNIQUE_SECURITY_INVARIANT/,
	);
});

test("file environment blocks absolute, traversal, and symlink escapes", async (t) => {
	const scratch = await mkdtemp(join(PROJECT_ROOT, ".pi-hardening-"));
	t.after(async () => rm(scratch, { recursive: true, force: true }));
	await mkdir(join(scratch, "inside"));
	await symlink("/etc", join(scratch, "outside"));

	const env = new ConfinedExecutionEnv({ cwd: scratch, root: PROJECT_ROOT });
	assert.equal((await env.absolutePath("inside/new.txt")).ok, true);
	assert.equal((await env.absolutePath("../../../../etc/passwd")).ok, false);
	assert.equal((await env.absolutePath("/etc/passwd")).ok, false);
	assert.equal((await env.absolutePath("outside/passwd")).ok, false);
});

test("bash write sandbox denies paths outside the configured root", async (t) => {
	const target = join(dirname(PROJECT_ROOT), `.pi-outside-${process.pid}`);
	t.after(async () => rm(target, { force: true }));
	const env = new ConfinedExecutionEnv({ cwd: PROJECT_ROOT, root: PROJECT_ROOT });
	const result = await env.exec(`printf blocked > '${target}'`, { timeout: 2 });
	assert.equal(result.ok, true);
	assert.notEqual(result.value.exitCode, 0);
	await assert.rejects(access(target));
});

test("run wall timeout aborts the active command and reports failure", async () => {
	const run = new PiRun({
		...options({
			tools: ["bash"],
			faux_scenario: "stall",
			run_timeout_ms: 250,
		}),
		id: "timeout-test",
	});
	const started = Date.now();
	await run.start();
	assert.equal(run.state, "failed");
	assert.match(run.error, /timed out/);
	assert.ok(Date.now() - started < 3_000);
});

test("empty final provider response is not reported as success", async () => {
	const run = new PiRun({
		...options({ faux_scenario: "empty" }),
		id: "empty-test",
	});
	await run.start();
	assert.equal(run.state, "failed");
	assert.match(run.error, /empty final response/);
});

test("a broken event listener cannot fail another run", async () => {
	const run = new PiRun({ ...options(), id: "listener-test" });
	run.subscribe(() => {
		throw new Error("client disconnected badly");
	});
	await run.start();
	assert.equal(run.state, "done");
	assert.match(run.result, /test goal/);
});

test("subscriptions replay only events after the supplied cursor", () => {
	const run = new PiRun({ ...options(), id: "cursor-test" });
	const first = run.emit("text", { delta: "first" });
	const second = run.emit("text", { delta: "second" });
	const replayed = [];
	const unsubscribe = run.subscribe((event) => replayed.push(event), first.seq);
	unsubscribe();
	assert.deepEqual(
		replayed.map((event) => event.seq),
		[second.seq],
	);
});

test("confirm-gated tools report preflight before execution", async () => {
	const run = new PiRun({
		...options({
			tools: ["bash"],
			confirm_tools: ["bash"],
			faux_scenario: "tool",
		}),
		id: "confirm-order-test",
	});
	const events = [];
	run.subscribe((event) => {
		events.push(event);
		if (event.type === "confirm_request") run.confirm(event.confirm_id, true);
	});
	await run.start();
	const awaiting = events.findIndex(
		(event) => event.type === "state" && event.state === "awaiting_confirm",
	);
	const started = events.findIndex(
		(event) => event.type === "tool" && event.phase === "start",
	);
	assert.ok(awaiting >= 0);
	assert.ok(started > awaiting);
	assert.equal(run.state, "done");
});

test("multiple gated calls are confirmed and executed sequentially", async () => {
	const run = new PiRun({
		...options({
			tools: ["bash"],
			confirm_tools: ["bash"],
			faux_scenario: "multi-tool",
		}),
		id: "multi-confirm-test",
	});
	const confirms = [];
	const starts = [];
	run.subscribe((event) => {
		if (event.type === "confirm_request") {
			confirms.push(event.confirm_id);
			run.confirm(event.confirm_id, true);
		}
		if (event.type === "tool" && event.phase === "start") starts.push(event.tool_call_id);
	});
	await run.start();
	assert.equal(run.state, "done");
	assert.equal(confirms.length, 2);
	assert.equal(starts.length, 2);
	assert.notEqual(confirms[0], confirms[1]);
});

test("HTTP server bounds JSON bodies and active runs", async (t) => {
	const server = createSidecarServer({ maxActiveRuns: 1, maxBodyBytes: 256 });
	server.listen(0, "127.0.0.1");
	await once(server, "listening");
	t.after(async () => {
		await server.cancelRuns();
		server.close();
	});
	const address = server.address();
	assert.equal(typeof address, "object");
	const base = `http://127.0.0.1:${address.port}`;

	const nullBody = await fetch(`${base}/runs`, {
		method: "POST",
		headers: { "content-type": "application/json" },
		body: "null",
	});
	assert.equal(nullBody.status, 400);

	const simpleCrossOriginBody = await fetch(`${base}/runs`, {
		method: "POST",
		headers: { "content-type": "text/plain" },
		body: JSON.stringify({ goal: "browser CSRF" }),
	});
	assert.equal(simpleCrossOriginBody.status, 415);

	const oversized = await fetch(`${base}/runs`, {
		method: "POST",
		headers: { "content-type": "application/json" },
		body: JSON.stringify({ goal: "x".repeat(300) }),
	});
	assert.equal(oversized.status, 413);

	const first = await fetch(`${base}/runs`, {
		method: "POST",
		headers: { "content-type": "application/json" },
		body: JSON.stringify({
			goal: "hold",
			faux_scenario: "stall",
			tools: ["bash"],
			confirm_tools: [],
			run_timeout_ms: 5_000,
		}),
	});
	assert.equal(first.status, 201);
	const firstRun = await first.json();

	const second = await fetch(`${base}/runs`, {
		method: "POST",
		headers: { "content-type": "application/json" },
		body: JSON.stringify({ goal: "too many", faux_scenario: "text", tools: [] }),
	});
	assert.equal(second.status, 429);

	const cancelled = await fetch(`${base}/runs/${firstRun.id}/cancel`, {
		method: "POST",
		headers: { "content-type": "application/json" },
		body: "{}",
	});
	assert.equal(cancelled.status, 200);
	assert.equal((await cancelled.json()).state, "cancelled");
});

test("configured bearer token protects every endpoint", async (t) => {
	const server = createSidecarServer({ token: "a".repeat(32) });
	server.listen(0, "127.0.0.1");
	await once(server, "listening");
	t.after(async () => {
		await server.cancelRuns();
		server.close();
	});
	const address = server.address();
	const base = `http://127.0.0.1:${address.port}`;
	assert.equal((await fetch(`${base}/health`)).status, 401);
	assert.equal(
		(
			await fetch(`${base}/health`, {
				headers: { authorization: `Bearer ${"a".repeat(32)}` },
			})
		).status,
		200,
	);
});
