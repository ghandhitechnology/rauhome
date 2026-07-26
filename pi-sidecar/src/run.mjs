import { contentText } from "@earendil-works/pi-ai";
import {
	AgentHarness,
	createBashTool,
	formatSkillsForSystemPrompt,
	createEditTool,
	createReadTool,
	createWriteTool,
	err,
	ExecutionError,
	FileError,
	JsonlSessionStorage,
	NodeExecutionEnv,
	ok,
	Session,
} from "@earendil-works/pi-agent-core/node";
import { existsSync, realpathSync, statSync } from "node:fs";
import { mkdir, realpath } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";
import { resolveModel } from "./models.mjs";

const ACTIVE_STATES = new Set(["running", "awaiting_confirm"]);
const TERMINAL_STATES = new Set(["done", "failed", "cancelled"]);
const MAX_HISTORY = 500;
const MAX_GOAL_CHARS = 100_000;
const MAX_SYSTEM_PROMPT_CHARS = 200_000;
const MAX_SKILLS = 64;
const MAX_SKILL_FIELD_CHARS = 100_000;
const MAX_SKILLS_TOTAL_CHARS = 200_000;
const MAX_TOOLS = 16;
const MAX_CONFIRM_TIMEOUT_MS = 10 * 60_000;
const MAX_RUN_TIMEOUT_MS = 60 * 60_000;
const MAX_TURNS = 100;

const MODULE_DIR = dirname(fileURLToPath(import.meta.url));
export const PROJECT_ROOT = realpathSync(process.env.PI_SIDECAR_ROOT ?? resolve(MODULE_DIR, "../.."));

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
	runTimeoutMs: 15 * 60_000,
};

function isWithin(root, candidate) {
	const rel = relative(root, candidate);
	return rel === "" || (!rel.startsWith(`..${sep}`) && rel !== ".." && !isAbsolute(rel));
}

/**
 * Resolve a possibly-new path without trusting symlinked existing prefixes.
 *
 * `realpath()` only accepts an existing target, but write tools necessarily
 * receive paths that do not exist yet. Walk upward until something exists,
 * resolve that prefix, then append the missing path components.
 */
async function canonicalCandidate(candidate) {
	let current = resolve(candidate);
	const missing = [];
	while (!existsSync(current)) {
		const parent = dirname(current);
		if (parent === current) break;
		missing.unshift(current.slice(parent.length + (parent.endsWith(sep) ? 0 : 1)));
		current = parent;
	}
	const base = await realpath(current);
	return resolve(base, ...missing);
}

function shellQuote(value) {
	return `'${String(value).replace(/'/g, `'\\''`)}'`;
}

function sandboxProfile(root) {
	const home = process.env.HOME ? resolve(process.env.HOME) : "";
	const writable = [
		root,
		"/tmp",
		"/private/tmp",
		"/private/var/tmp",
		home && resolve(home, "Library/Caches"),
		home && resolve(home, ".cache"),
	].filter(Boolean);
	const subpaths = writable
		.map((path) => `(subpath ${JSON.stringify(path)})`)
		.join(" ");
	return [
		"(version 1)",
		"(allow default)",
		"(deny file-write*)",
		`(allow file-write* ${subpaths})`,
		'(allow file-write-data (literal "/dev/null") (literal "/dev/zero") (regex #"^/dev/tty.*"))',
	].join("\n");
}

/**
 * pi's stock NodeExecutionEnv resolves absolute paths anywhere on the host.
 * This wrapper makes file-tool containment a property of the environment,
 * not a prompt convention, and runs bash under macOS seatbelt.
 */
export class ConfinedExecutionEnv extends NodeExecutionEnv {
	constructor({ cwd, root = PROJECT_ROOT }) {
		super({ cwd });
		this.root = root;
		this.profile = sandboxProfile(root);
	}

	async absolutePath(path) {
		try {
			if (typeof path !== "string" || !path.trim()) {
				return err(new FileError("invalid", "path must be a non-empty string", String(path ?? "")));
			}
			const candidate = isAbsolute(path) ? path : resolve(this.cwd, path);
			const canonical = await canonicalCandidate(candidate);
			if (!isWithin(this.root, canonical)) {
				return err(
					new FileError(
						"permission_denied",
						`path escapes the configured root: ${path}`,
						canonical,
					),
				);
			}
			return ok(canonical);
		} catch (error) {
			return err(new FileError("invalid", String(error), String(path ?? ""), error));
		}
	}

	async exec(command, options) {
		const cwdResult = await this.absolutePath(options?.cwd ?? this.cwd);
		if (!cwdResult.ok) {
			return err(new ExecutionError("spawn_error", cwdResult.error.message, cwdResult.error));
		}
		if (!existsSync("/usr/bin/sandbox-exec")) {
			if (process.env.PI_SIDECAR_ALLOW_UNSANDBOXED !== "1") {
				return err(
					new ExecutionError(
						"spawn_error",
						"sandbox-exec is unavailable; refusing an unconfined bash tool",
					),
				);
			}
			return super.exec(command, { ...options, cwd: cwdResult.value });
		}
		const wrapped = [
			"/usr/bin/sandbox-exec",
			"-p",
			shellQuote(this.profile),
			"/bin/bash",
			"-c",
			shellQuote(command),
		].join(" ");
		return super.exec(wrapped, { ...options, cwd: cwdResult.value });
	}
}

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
		this.timedOut = false;
		this.timeoutTimer = undefined;
		this.env = undefined;
		this.toolPhases = new Map();
		this.closed = false;
		this.structuredResult = undefined;
		this.sessionPath = "";
		this.completion = new Promise((resolve) => {
			this.resolveCompletion = resolve;
		});
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
			completion: this.structuredResult ?? null,
			session_path: this.sessionPath,
		};
	}

	subscribe(listener, afterSeq = 0) {
		const pending = this.pendingConfirm;
		let replayed = false;
		for (const event of this.history) {
			if (event.seq <= afterSeq) continue;
			if (pending && event.type === "confirm_request" && event.confirm_id === pending.id) replayed = true;
			this.notify(listener, event);
		}
		// A long run pushes its own confirm request out of the replay window. Without
		// it a subscriber attaching now has nothing to approve and the gate can only
		// clear on its timeout, so re-announce the one that is still open.
		if (pending && !replayed && pending.event?.seq > afterSeq) {
			this.notify(listener, pending.event);
		}
		if (TERMINAL_STATES.has(this.state)) return () => {};
		this.listeners.add(listener);
		return () => this.listeners.delete(listener);
	}

	notify(listener, event) {
		try {
			listener(event);
			return true;
		} catch {
			this.listeners.delete(listener);
			return false;
		}
	}

	emit(type, payload = {}) {
		const event = { seq: ++this.seq, type, ts: Date.now(), ...payload };
		this.history.push(event);
		if (this.history.length > MAX_HISTORY) this.history.splice(0, this.history.length - MAX_HISTORY);
		for (const listener of [...this.listeners]) this.notify(listener, event);
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
		this.timeoutTimer = setTimeout(() => {
			if (!ACTIVE_STATES.has(this.state)) return;
			this.timedOut = true;
			this.finish("failed", "", `run timed out after ${this.options.runTimeoutMs} ms`);
			this.settleConfirm(false, "run timeout");
			void this.abortHarness();
		}, this.options.runTimeoutMs);
		try {
			const { models, model } = await resolveModel(this.options);
			// Cancellation/timeout can land while a provider module is loading.
			// Do not create a harness or make a billable request after settlement.
			if (!ACTIVE_STATES.has(this.state)) return;
			const env = new ConfinedExecutionEnv({ cwd: this.cwd, root: this.options.root });
			this.env = env;
			const sessionDir = resolve(this.options.root, "memories", "pi-sessions");
			await mkdir(sessionDir, { recursive: true });
			this.sessionPath = resolve(sessionDir, `${this.id}.jsonl`);
			const storage = existsSync(this.sessionPath)
				? await JsonlSessionStorage.open(env, this.sessionPath)
				: await JsonlSessionStorage.create(env, this.sessionPath, {
						cwd: this.cwd,
						sessionId: this.id,
						metadata: { runId: this.id, createdAt: new Date().toISOString() },
					});
			const session = new Session(storage);
			const tools = this.options.tools.map((name) => {
				const factory = TOOL_FACTORIES[name];
				if (!factory) throw new Error(`unknown tool: ${name}`);
				const tool = factory();
				// Pi executes tool batches in parallel by default. Rau exposes a
				// single confirmation gate, and file/shell mutations also need
				// deterministic ordering, so serialize the entire batch.
				return { ...tool, executionMode: "sequential" };
			});
			tools.push(this.createFinishTool());
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
			if (!ACTIVE_STATES.has(this.state)) {
				await this.abortHarness();
				return;
			}
			this.harness.subscribe((event) => this.onAgentEvent(event));
			this.harness.on("tool_call", (event) => this.onToolCall(event));
			this.harness.on("before_provider_request", () => {
				if (this.turns >= this.options.maxTurns) {
					this.overBudget = true;
					throw new Error(`turn budget of ${this.options.maxTurns} exhausted`);
				}
				return undefined;
			});

			const message = await this.harness.prompt(this.goal);
			this.settle(message);
		} catch (error) {
			this.fail(error);
		} finally {
			clearTimeout(this.timeoutTimer);
			this.settleConfirm(false, "run ended");
			try {
				await this.env?.cleanup();
			} catch (error) {
				this.emit("warning", { message: `environment cleanup failed: ${String(error)}` });
			}
			this.toolPhases.clear();
			this.closed = true;
			for (const listener of [...this.listeners]) {
				this.notify(listener, { seq: ++this.seq, type: "close", ts: Date.now() });
			}
			this.listeners.clear();
			this.resolveCompletion();
		}
	}

	createFinishTool() {
		return {
			name: "finish",
			label: "finish",
			description: "Return the structured completion contract after verification.",
			executionMode: "sequential",
			parameters: {
				type: "object",
				required: ["outcome", "summary"],
				properties: {
					outcome: { type: "string", enum: ["completed", "failed", "blocked"] },
					summary: { type: "string" },
					artifacts: { type: "array", items: { type: "string" } },
					mutations: { type: "array", items: { type: "string" } },
					verification: { type: "array", items: { type: "string" } },
					blockers: { type: "array", items: { type: "string" } },
					remaining_risks: { type: "array", items: { type: "string" } },
				},
			},
			execute: async (_callId, input) => {
				const fields = ["artifacts", "mutations", "verification", "blockers", "remaining_risks"];
				const completion = {
					outcome: String(input.outcome ?? "completed"),
					summary: String(input.summary ?? "").slice(0, 100_000),
				};
				for (const field of fields) {
					completion[field] = Array.isArray(input[field])
						? input[field].filter((value) => typeof value === "string").slice(0, 100)
						: [];
				}
				this.structuredResult = completion;
				return {
					content: [{ type: "text", text: "Structured completion recorded." }],
					details: completion,
				};
			},
		};
	}

	/** pi never injects the skill listing itself — the application owns that block. */
	buildSystemPrompt(resources) {
		const available = resources.skills ?? [];
		const skills = formatSkillsForSystemPrompt(available);
		// pi's formatter advertises only names and file locations. Rau skills
		// can be synthesized in memory, and a run may intentionally omit the
		// read tool, so carry supplied bodies as well instead of silently
		// dropping the capability at the bridge.
		const bodies = available
			.filter((skill) => skill.content)
			.map((skill) => `## Skill: ${skill.name}\n${skill.content}`)
			.join("\n\n");
		return [
			this.options.systemPrompt,
			"Before stopping, call finish with outcome, summary, artifacts, mutations, verification, blockers, and remaining risks.",
			skills,
			bodies,
		].filter(Boolean).join("\n\n");
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
			const gated = this.options.confirmTools.includes(event.toolName);
			this.toolPhases.set(event.toolCallId, gated ? "preflight" : "running");
			if (gated) {
				this.emit("tool", {
					phase: "preflight",
					tool: event.toolName,
					tool_call_id: event.toolCallId,
					args: event.args,
				});
			} else {
				this.setState("running", `running ${event.toolName}`);
				this.emit("tool", {
					phase: "start",
					tool: event.toolName,
					tool_call_id: event.toolCallId,
					args: event.args,
				});
			}
			return;
		}
		if (event.type === "tool_execution_end") {
			const phase = this.toolPhases.get(event.toolCallId);
			this.toolPhases.delete(event.toolCallId);
			this.emit("tool", {
				phase: phase === "blocked" ? "blocked" : "end",
				tool: event.toolName,
				tool_call_id: event.toolCallId,
				ok: !event.isError,
			});
			return;
		}
		if (event.type === "turn_end") {
			this.turns += 1;
			this.setState("running", `turn ${this.turns}`);
			// pi's agent loop runs until the model stops calling tools; there is no
			// turn budget inside it, so the ceiling has to be enforced from out here.
			if (this.turns >= this.options.maxTurns) {
				this.overBudget = true;
			}
		}
	}

	async onToolCall(event) {
		// pi invokes this hook before consulting the abort signal, so a run
		// timeout can deliver a gated tool call after the run already settled.
		// Parking a confirm here would emit a spurious request on a finished run
		// and stall the loop until the confirm timeout clears it.
		if (this.cancelled || TERMINAL_STATES.has(this.state)) {
			return { block: true, reason: this.cancelled ? "run cancelled" : "run already finished" };
		}
		if (!this.options.confirmTools.includes(event.toolName)) return undefined;
		const approved = await this.requestConfirm(event);
		if (approved) {
			this.toolPhases.set(event.toolCallId, "running");
			this.setState("running", `running ${event.toolName}`);
			this.emit("tool", {
				phase: "start",
				tool: event.toolName,
				tool_call_id: event.toolCallId,
				args: event.input,
			});
			return undefined;
		}
		this.toolPhases.set(event.toolCallId, "blocked");
		this.setState("running", `${event.toolName} blocked`);
		return { block: true, reason: "user denied or confirm timed out" };
	}

	requestConfirm(event) {
		const id = `${this.id}:${event.toolCallId}`;
		const summary = summarize(event);
		return new Promise((resolve) => {
			const timer = setTimeout(() => this.settleConfirm(false, "timeout"), this.options.confirmTimeoutMs);
			this.pendingConfirm = { id, tool: event.toolName, summary, input: event.input, resolve, timer };
			this.setState("awaiting_confirm", summary);
			this.pendingConfirm.event = this.emit("confirm_request", {
				confirm_id: id,
				tool: event.toolName,
				summary,
				input: event.input,
			});
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
			} else if (this.timedOut) {
				this.finish("failed", "", `run timed out after ${this.options.runTimeoutMs} ms`);
			} else {
				this.finish("cancelled", "", "");
			}
			return;
		}
		if (message.stopReason === "error") {
			if (this.overBudget) {
				this.finish("failed", text, `turn budget of ${this.options.maxTurns} exhausted`);
				return;
			}
			this.finish("failed", text, message.errorMessage || "provider error");
			return;
		}
		if (message.stopReason === "length") {
			this.finish("failed", text, "provider response hit the output token limit");
			return;
		}
		if (!text && !this.structuredResult?.summary) {
			this.finish("failed", "", "provider returned an empty final response");
			return;
		}
		const summary = this.structuredResult?.summary || text;
		const outcome = this.structuredResult?.outcome;
		if (outcome === "failed" || outcome === "blocked") {
			this.finish("failed", summary, outcome === "blocked" ? "blocked" : "worker reported failure");
			return;
		}
		this.finish("done", summary, "");
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
		this.emit("result", {
			state,
			result,
			error,
			completion: this.structuredResult ?? null,
			session_path: this.sessionPath,
		});
	}
}

function summarize(event) {
	const input = event.input && typeof event.input === "object" && !Array.isArray(event.input) ? event.input : {};
	if (typeof input.command === "string") return `run: ${input.command}`;
	if (typeof input.path === "string") return `${event.toolName}: ${input.path}`;
	return `${event.toolName}: ${JSON.stringify(input).slice(0, 200)}`;
}

function finiteInteger(value, name, { min, max }) {
	const number = Number(value);
	if (!Number.isSafeInteger(number) || number < min || number > max) {
		throw new Error(`${name} must be an integer between ${min} and ${max}`);
	}
	return number;
}

function stringField(value, name, max, { optional = false } = {}) {
	if (value === undefined && optional) return undefined;
	if (typeof value !== "string") throw new Error(`${name} must be a string`);
	if (value.length > max) throw new Error(`${name} exceeds ${max} characters`);
	return value;
}

function stringArray(value, name, { allowed, max = MAX_TOOLS }) {
	if (!Array.isArray(value) || value.length > max) throw new Error(`${name} must be an array of at most ${max} items`);
	const out = [];
	for (const item of value) {
		if (typeof item !== "string" || !allowed.has(item)) throw new Error(`unknown ${name} entry: ${String(item)}`);
		if (!out.includes(item)) out.push(item);
	}
	return out;
}

function resolveCwd(value, root) {
	const raw = value === undefined ? root : stringField(value, "cwd", 4096);
	const candidate = isAbsolute(raw) ? raw : resolve(root, raw);
	let canonical;
	try {
		canonical = realpathSync(candidate);
	} catch {
		throw new Error(`cwd does not exist: ${raw}`);
	}
	if (!statSync(canonical).isDirectory()) throw new Error(`cwd is not a directory: ${raw}`);
	if (!isWithin(root, canonical)) throw new Error(`cwd escapes configured root: ${raw}`);
	return canonical;
}

function normalizeSkills(value, root) {
	if (!Array.isArray(value) || value.length > MAX_SKILLS) {
		throw new Error(`skills must be an array of at most ${MAX_SKILLS} items`);
	}
	let total = 0;
	return value.map((skill, index) => {
		if (!skill || typeof skill !== "object" || Array.isArray(skill)) {
			throw new Error(`skills[${index}] must be an object`);
		}
		const normalized = {
			name: stringField(skill.name ?? "", `skills[${index}].name`, 200),
			description: stringField(skill.description ?? "", `skills[${index}].description`, 4000),
			content: stringField(skill.content ?? "", `skills[${index}].content`, MAX_SKILL_FIELD_CHARS),
			filePath: stringField(skill.filePath ?? "", `skills[${index}].filePath`, 4096),
		};
		if (!normalized.name.trim()) throw new Error(`skills[${index}].name must not be empty`);
		total += normalized.content.length;
		if (total > MAX_SKILLS_TOTAL_CHARS) {
			throw new Error(`skill content exceeds ${MAX_SKILLS_TOTAL_CHARS} characters in total`);
		}
		if (normalized.filePath) {
			const candidate = isAbsolute(normalized.filePath)
				? normalized.filePath
				: resolve(root, normalized.filePath);
			const canonical = realpathSync(candidate);
			if (!isWithin(root, canonical)) {
				throw new Error(`skills[${index}].filePath escapes configured root`);
			}
			if (!statSync(canonical).isFile()) {
				throw new Error(`skills[${index}].filePath is not a file`);
			}
			normalized.filePath = canonical;
		}
		return normalized;
	});
}

export function withDefaults(body, root = PROJECT_ROOT) {
	if (!body || typeof body !== "object" || Array.isArray(body)) {
		throw new Error("request body must be a JSON object");
	}
	const goal = stringField(body.goal ?? "", "goal", MAX_GOAL_CHARS).trim();
	if (!goal) throw new Error("empty goal");
	const provider = stringField(body.provider ?? DEFAULTS.provider, "provider", 100);
	const model = stringField(body.model ?? DEFAULTS.model, "model", 300);
	if (!/^[a-z0-9][a-z0-9-]*$/i.test(provider)) throw new Error("invalid provider id");
	if (!model.trim() || /[\0\r\n]/.test(model)) throw new Error("invalid model id");
	const tools = stringArray(body.tools ?? DEFAULTS.tools, "tools", {
		allowed: new Set(Object.keys(TOOL_FACTORIES)),
	});
	const requestedConfirmTools = stringArray(body.confirm_tools ?? DEFAULTS.confirmTools, "confirm_tools", {
		allowed: new Set(tools),
	});
	// Callers may add gates but may never disable the baseline gates around
	// process execution and mutation tools.
	const mandatoryConfirmTools = DEFAULTS.confirmTools.filter((name) => tools.includes(name));
	const confirmTools = [...new Set([...requestedConfirmTools, ...mandatoryConfirmTools])];
	return {
		goal,
		root,
		cwd: resolveCwd(body.cwd, root),
		provider,
		model,
		fauxScenario: stringField(body.faux_scenario ?? DEFAULTS.fauxScenario, "faux_scenario", 100),
		systemPrompt: stringField(
			body.system_prompt ?? "You are a focused coding agent. Finish the goal, then report briefly.",
			"system_prompt",
			MAX_SYSTEM_PROMPT_CHARS,
		),
		skills: normalizeSkills(body.skills ?? [], root),
		tools,
		confirmTools,
		confirmTimeoutMs: finiteInteger(body.confirm_timeout_ms ?? DEFAULTS.confirmTimeoutMs, "confirm_timeout_ms", {
			min: 100,
			max: MAX_CONFIRM_TIMEOUT_MS,
		}),
		maxTurns: finiteInteger(body.max_turns ?? DEFAULTS.maxTurns, "max_turns", { min: 1, max: MAX_TURNS }),
		runTimeoutMs: finiteInteger(body.run_timeout_ms ?? DEFAULTS.runTimeoutMs, "run_timeout_ms", {
			min: 250,
			max: MAX_RUN_TIMEOUT_MS,
		}),
	};
}

export { ACTIVE_STATES, TERMINAL_STATES };
