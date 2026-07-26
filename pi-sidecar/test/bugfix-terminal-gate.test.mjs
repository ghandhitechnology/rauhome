import assert from "node:assert/strict";
import test from "node:test";
import { PiRun, PROJECT_ROOT, withDefaults } from "../src/run.mjs";

function options(body = {}) {
	return withDefaults(
		{
			goal: "test goal",
			tools: ["bash"],
			confirm_tools: ["bash"],
			faux_scenario: "text",
			confirm_timeout_ms: 100,
			run_timeout_ms: 5_000,
			...body,
		},
		PROJECT_ROOT,
	);
}

// pi's loop invokes the tool_call hook before it consults the abort signal, so
// a run timeout can hand a gated tool call to a run that already settled. The
// gate must refuse outright instead of parking a confirm nobody can answer:
// the request would linger until the confirm timeout and accept approvals
// against a run that already reported its result.
test("a terminal run blocks gated tool calls instead of parking a confirm", async () => {
	const run = new PiRun({ ...options(), id: "terminal-gate-test" });
	run.finish("failed", "", "run timed out after 1 ms");
	const decision = await run.onToolCall({
		toolName: "bash",
		toolCallId: "late-1",
		input: { command: "echo late" },
	});
	assert.deepEqual(decision, { block: true, reason: "run already finished" });
	assert.equal(run.pendingConfirm, undefined);
	assert.equal(
		run.history.some((event) => event.type === "confirm_request"),
		false,
		"a finished run must not emit confirm requests",
	);
	assert.equal(run.confirm(undefined, true), false, "nothing is left to approve");
});

test("a cancelled run keeps the cancelled block reason", async () => {
	const run = new PiRun({ ...options(), id: "cancel-gate-test" });
	assert.equal(await run.cancel(), true);
	const decision = await run.onToolCall({
		toolName: "bash",
		toolCallId: "late-2",
		input: { command: "echo late" },
	});
	assert.deepEqual(decision, { block: true, reason: "run cancelled" });
	assert.equal(run.pendingConfirm, undefined);
});

test("a live run still parks and releases a confirm gate", async () => {
	const run = new PiRun({ ...options(), id: "live-gate-test" });
	const gated = run.onToolCall({
		toolName: "bash",
		toolCallId: "live-1",
		input: { command: "echo hi" },
	});
	assert.equal(run.state, "awaiting_confirm");
	const confirmId = run.pendingConfirm?.id;
	assert.ok(confirmId);
	assert.equal(run.confirm(confirmId, true), true);
	assert.equal(await gated, undefined, "approval releases the hook");
	assert.equal(run.state, "running");
});
