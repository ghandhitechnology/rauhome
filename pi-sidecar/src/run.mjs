import { contentText } from "@earendil-works/pi-ai";
import {
	AgentHarness,
	createBashTool,
	formatSkillsForSystemPrompt,
	createEditTool,
	createReadTool,
	createWriteTool,
	InMemorySessionStorage,
	NodeExecutionEnv,
	Session,
} from "@earendil-works/pi-agent-core/node";
import { resolveModel } from "./models.mjs";

const ACTIVE_STATES = new Set(["running", "awaiting_confirm"]);
const TERMINAL_STATES = new Set(["done", "failed", "cancelled"]);
const MAX_HISTORY = 500;

const TOOL_FACTORIES = {
	bash: createBashTool,
	read: createReadTool,
	write: createWriteTool,
	edit: createEditTool,
};

export const DEFAULTS = {
	provider: "faux",
	model: "faux-1",
	fauxScenario: "tool",
	tools: ["bash", "read", "write", "edit"],
	confirmTools: ["bash", "write", "edit"],
	confirmTimeoutMs: 45_000,
	maxTurns: 24,
};

/**
 * One pi agent run, projected onto Rau's job vocabulary.
 *
 * pi's harness has no notion of a job: it has a phase (`idle`/`turn`/...) and a
 * promise that settles. The run owns the state machine instead, and treats a
 * terminal state as immutable so a cancel racing the harness's own settlement
 * cannot resurrect a finished run.
 */
export class PiRun {
	constructor(options) {
		this.id = options.id;
		this.goal = options.goal;
		this.cwd = options.cwd;
		this.state = "running";
		this.progress = "starting";
		this.result = "";
		this.error = "";
		this.turns = 0;
		this.created = Date.now();
		this.updated = this.created;
		this.options = options;
		this.seq = 0;
		this.history = [];
		this.listeners = new Set();
		this.harness = undefined;
		this.pendingConfirm = undefined;
		this.cancelled = false;
		this.overBudget = false;
	}

	snapshot() {
		return {
			id: this.id,
			goal: this.goal,
			state: this.state,
			progress: this.progress,
			result: this.result,
			error: this.error,
			turns: this.turns,
			created: this.created,
			updated: this.updated,
			confirm: this.pendingConfirm
				? { id: this.pendingConfirm.id, tool: this.pendingConfirm.tool, summary: this.pendingConfirm.summary }
				: null,
		};
	}

	subscribe(listener) {
		const pending = this.pendingConfirm;
		let replayed = false;
		for (const event of this.history) {
			if (pending && event.type === "confirm_request" && event.confirm_id === pending.id) replayed = true;
			listener(event);
		}
		// A long run pushes its own confirm request out of the replay window. Without
		// it a subscriber attaching now has nothing to approve and the gate can only
		// clear on its timeout, so re-announce the one that is still open.
		if (pending && !replayed) {
			listener({
				seq: this.seq,
				type: "confirm_request",
				ts: Date.now(),
				confirm_id: pending.id,
				tool: pending.tool,
				summary: pending.summary,
				input: pending.input,
			});
		}
		if (TERMINAL_STATES.has(this.state)) return () => {};
		this.listeners.add(listener);
		return () => this.listeners.delete(listener);
	}

	emit(type, payload = {}) {
		const event = { seq: ++this.seq, type, ts: Date.now(), ...payload };
		this.history.push(event);
		if (this.history.length > MAX_HISTORY) this.history.splice(0, this.history.length - MAX_HISTORY);
		for (const listener of this.listeners) listener(event);
		return event;
	}

	setState(state, progress) {
		if (TERMINAL_STATES.has(this.state)) return;
		this.state = state;
		if (progress !== undefined) this.progress = progress;
		this.updated = Date.now();
		this.emit("state", { state: this.state, progress: this.progress });
	}

	async start() {
		try {
			const { models, model } = await resolveModel(this.options);
			const env = new NodeExecutionEnv({ cwd: this.cwd });
			const session = new Session(
				new InMemorySessionStorage({ metadata: { id: this.id, createdAt: new Date().toISOString() } }),
			);
			const tools = this.options.tools.map((name) => {
				const factory = TOOL_FACTORIES[name];
				if (!factory) throw new Error(`unknown tool: ${name}`);
				return factory();
			});
			this.harness = new AgentHarness({
				session,
				models,
				model,
				tools,
				toolContext: { env },
				// A callback, not a string: pi re-resolves it for every provider
				// request, which is what lets Rau's live soul and emotion ride along
				// on each turn instead of freezing at the moment the run started.
				systemPrompt: ({ resources }) => this.buildSystemPrompt(resources),
				resources: { skills: this.options.skills },
			});
			this.harness.subscribe((event) => this.onAgentEvent(event));
			this.harness.on("tool_call", (event) => this.onToolCall(event));

			const message = await this.harness.prompt(this.goal);
			this.settle(message);
		} catch (error) {
			this.fail(error);
		} finally {
			this.settleConfirm(false, "run ended");
			for (const listener of this.listeners) listener({ seq: ++this.seq, type: "close", ts: Date.now() });
			this.listeners.clear();
		}
	}

	/** pi never injects the skill listing itself — the application owns that block. */
	buildSystemPrompt(resources) {
		const skills = formatSkillsForSystemPrompt(resources.skills ?? []);
		return skills ? `${this.options.systemPrompt}\n\n${skills}` : this.options.systemPrompt;
	}

	onAgentEvent(event) {
		// A cancelled run still sees the loop unwind — the aborted tool result and
		// its turn end. Reporting those would contradict the settled result.
		if (TERMINAL_STATES.has(this.state)) return;
		if (event.type === "message_update" && event.assistantMessageEvent?.type === "text_delta") {
			this.emit("text", { delta: event.assistantMessageEvent.delta });
			return;
		}
		if (event.type === "tool_execution_start") {
			this.setState("running", `running ${event.toolName}`);
			this.emit("tool", { phase: "start", tool: event.toolName, args: event.args });
			return;
		}
		if (event.type === "tool_execution_end") {
			this.emit("tool", { phase: "end", tool: event.toolName, ok: !event.isError });
			return;
		}
		if (event.type === "turn_end") {
			this.turns += 1;
			this.setState("running", `turn ${this.turns}`);
			// pi's agent loop runs until the model stops calling tools; there is no
			// turn budget inside it, so the ceiling has to be enforced from out here.
			if (this.turns >= this.options.maxTurns) {
				this.overBudget = true;
				this.abortHarness();
			}
		}
	}

	async onToolCall(event) {
		if (this.cancelled) return { block: true, reason: "run cancelled" };
		if (!this.options.confirmTools.includes(event.toolName)) return undefined;
		const approved = await this.requestConfirm(event);
		this.setState("running", `running ${event.toolName}`);
		return approved ? undefined : { block: true, reason: "user denied or confirm timed out" };
	}

	requestConfirm(event) {
		const id = `${this.id}:${event.toolCallId}`;
		const summary = summarize(event);
		return new Promise((resolve) => {
			const timer = setTimeout(() => this.settleConfirm(false, "timeout"), this.options.confirmTimeoutMs);
			this.pendingConfirm = { id, tool: event.toolName, summary, input: event.input, resolve, timer };
			this.setState("awaiting_confirm", summary);
			this.emit("confirm_request", { confirm_id: id, tool: event.toolName, summary, input: event.input });
		});
	}

	settleConfirm(approved, reason) {
		const pending = this.pendingConfirm;
		if (!pending) return false;
		this.pendingConfirm = undefined;
		clearTimeout(pending.timer);
		this.emit("confirm_result", { confirm_id: pending.id, approved, reason });
		pending.resolve(approved);
		return true;
	}

	confirm(confirmId, approved) {
		if (!this.pendingConfirm) return false;
		if (confirmId && this.pendingConfirm.id !== confirmId) return false;
		return this.settleConfirm(approved, approved ? "approved" : "denied");
	}

	async cancel() {
		if (!ACTIVE_STATES.has(this.state)) return false;
		this.cancelled = true;
		// Settled before the abort: `abort()` waits for the run promise, which
		// only resolves after `start()` closes the event stream, so a result
		// emitted afterwards would reach nobody.
		this.finish("cancelled", "", "");
		// The confirm gate must be released too. A run parked inside the
		// tool_call hook can only settle once that hook returns, and pi does not
		// pass the abort signal to hook handlers — aborting first deadlocks.
		this.settleConfirm(false, "cancelled");
		await this.abortHarness();
		return true;
	}

	async abortHarness() {
		try {
			await this.harness?.abort();
		} catch (error) {
			this.emit("warning", { message: `abort failed: ${String(error)}` });
		}
	}

	settle(message) {
		if (TERMINAL_STATES.has(this.state)) return;
		const text = contentText(message.content).trim();
		if (message.stopReason === "aborted") {
			if (this.overBudget) {
				this.finish("failed", "", `turn budget of ${this.options.maxTurns} exhausted`);
			} else {
				this.finish("cancelled", "", "");
			}
			return;
		}
		if (message.stopReason === "error") {
			this.finish("failed", text, message.errorMessage || "provider error");
			return;
		}
		this.finish("done", text, "");
	}

	fail(error) {
		if (TERMINAL_STATES.has(this.state)) return;
		this.finish("failed", "", error instanceof Error ? error.message : String(error));
	}

	finish(state, result, error) {
		this.result = result;
		this.error = error;
		this.state = state;
		this.progress = state;
		this.updated = Date.now();
		this.emit("state", { state, progress: this.progress });
		this.emit("result", { state, result, error });
	}
}

function summarize(event) {
	const input = event.input ?? {};
	if (typeof input.command === "string") return `run: ${input.command}`;
	if (typeof input.path === "string") return `${event.toolName}: ${input.path}`;
	return `${event.toolName}: ${JSON.stringify(input).slice(0, 200)}`;
}

export function withDefaults(body) {
	const goal = String(body.goal ?? "").trim();
	if (!goal) throw new Error("empty goal");
	return {
		goal,
		cwd: body.cwd ?? process.cwd(),
		provider: body.provider ?? DEFAULTS.provider,
		model: body.model ?? DEFAULTS.model,
		fauxScenario: body.faux_scenario ?? DEFAULTS.fauxScenario,
		systemPrompt: body.system_prompt ?? "You are a focused coding agent. Finish the goal, then report briefly.",
		skills: body.skills ?? [],
		tools: body.tools ?? DEFAULTS.tools,
		confirmTools: body.confirm_tools ?? DEFAULTS.confirmTools,
		confirmTimeoutMs: Number(body.confirm_timeout_ms ?? DEFAULTS.confirmTimeoutMs),
		maxTurns: Number(body.max_turns ?? DEFAULTS.maxTurns),
	};
}

export { ACTIVE_STATES, TERMINAL_STATES };
