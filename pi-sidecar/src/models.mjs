import { createModels, fauxAssistantMessage, fauxProvider, fauxText, fauxToolCall } from "@earendil-works/pi-ai";
import { getBuiltinModel } from "@earendil-works/pi-ai/providers/all";

/**
 * Scripted faux responses so the bridge can be driven end to end without any
 * provider credentials. Each scenario is a sequence of turns; the last turn
 * must stop calling tools or the agent loop never terminates.
 */
const SCENARIOS = {
	tool: [
		(context) =>
			fauxAssistantMessage([
				fauxText("Checking the working tree before answering."),
				fauxToolCall("bash", { command: `echo ${shellQuote(`goal: ${goalOf(context)}`)} && ls -1 | head -3` }),
			]),
		(context) => fauxAssistantMessage(`Done. Goal was: ${goalOf(context)}`),
	],
	text: [(context) => fauxAssistantMessage(`Done. Goal was: ${goalOf(context)}`)],
	stall: [
		() =>
			fauxAssistantMessage([
				fauxText("Starting a long-running command."),
				fauxToolCall("bash", { command: "sleep 60" }),
			]),
		() => fauxAssistantMessage("Finished the long command."),
	],
};

export const FAUX_SCENARIOS = Object.keys(SCENARIOS);

/**
 * The goal is caller text and the scripted turns put it inside a command a real
 * shell executes, so it has to be quoted rather than interpolated.
 */
function shellQuote(value) {
	return `'${value.replace(/'/g, `'\\''`)}'`;
}

function goalOf(context) {
	const first = context.messages.find((message) => message.role === "user");
	if (!first) return "";
	const content = first.content;
	if (typeof content === "string") return content;
	return content
		.filter((block) => block.type === "text")
		.map((block) => block.text)
		.join(" ")
		.slice(0, 200);
}

let fauxSeq = 0;

/**
 * Resolve a model plus the `Models` collection that can stream it.
 *
 * `faux` runs entirely offline against a scripted provider. Every other
 * provider id resolves through pi's builtin catalog, and auth is left to pi's
 * own provider credential lookup, so the sidecar never handles API keys.
 */
export async function resolveModel({ provider, model, fauxScenario }) {
	const models = createModels();
	if (provider === "faux") {
		const scenario = SCENARIOS[fauxScenario ?? "tool"];
		if (!scenario) throw new Error(`unknown faux scenario: ${fauxScenario}`);
		// Each run gets its own provider id: a shared faux provider would
		// interleave two runs' scripted turns into one response queue.
		const faux = fauxProvider({ provider: `faux-${++fauxSeq}` });
		faux.setResponses(scenario);
		models.setProvider(faux.provider);
		return { models, model: faux.getModel() };
	}

	const resolved = getBuiltinModel(provider, model);
	if (!resolved) throw new Error(`unknown model: ${provider}/${model}`);
	const factory = await loadProviderFactory(provider);
	models.setProvider(factory());
	return { models, model: resolved };
}

async function loadProviderFactory(provider) {
	const module = await import(`@earendil-works/pi-ai/providers/${provider}`);
	const name = `${provider.replace(/-([a-z])/g, (_, c) => c.toUpperCase())}Provider`;
	const factory = module[name];
	if (typeof factory !== "function") throw new Error(`provider ${provider} exposes no ${name}()`);
	return factory;
}
