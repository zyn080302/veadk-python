/** Public Studio configuration only: no credentials or analysis-model options. */
export interface GlobalContextConfig {
  mode?: "auto";
  summary_model?: string;
  context_window?: number;
  input_limit?: number;
  output_reserve?: number;
  summary_context_window?: number;
  summary_input_limit?: number;
  media_token_reserve?: number;
  safety_margin?: number;
  keep_recent_turns?: number;
  summary_max_tokens?: number;
  max_summary_calls?: number;
  target_ratio?: number;
  trigger_ratio?: number;
  summary_trigger_ratio?: number;
  summary_timeout_seconds?: number;
  summary_time_budget_seconds?: number;
}

const ERROR = "Invalid Studio global context configuration";
const INTEGER_BOUNDS: Readonly<Record<string, readonly [number, number]>> = {
  context_window: [1, Number.MAX_SAFE_INTEGER],
  input_limit: [1, Number.MAX_SAFE_INTEGER],
  output_reserve: [1, Number.MAX_SAFE_INTEGER],
  summary_context_window: [1, Number.MAX_SAFE_INTEGER],
  summary_input_limit: [1, Number.MAX_SAFE_INTEGER],
  media_token_reserve: [1, Number.MAX_SAFE_INTEGER],
  safety_margin: [0, Number.MAX_SAFE_INTEGER],
  keep_recent_turns: [1, Number.MAX_SAFE_INTEGER],
  summary_max_tokens: [128, 8192],
  max_summary_calls: [1, 4],
};
const NUMBER_BOUNDS: Readonly<Record<string, number>> = {
  target_ratio: 1,
  trigger_ratio: 1,
  summary_trigger_ratio: 1,
  summary_timeout_seconds: 60,
  summary_time_budget_seconds: 90,
};

/** Mirror veadk.extensions.harness.global_context at the editable Draft boundary.
 * Throw a fixed message so untrusted imported values never enter error output. */
export function normalizeGlobalContext(
  value: unknown,
): GlobalContextConfig | undefined {
  if (value == null) return undefined;
  if (typeof value !== "object" || Array.isArray(value)) throw new Error(ERROR);
  const result: Record<string, string | number> = {};
  for (const [key, item] of Object.entries(value)) {
    if (Object.prototype.hasOwnProperty.call(INTEGER_BOUNDS, key)) {
      const [min, max] = INTEGER_BOUNDS[key];
      if (
        typeof item !== "number" ||
        !Number.isSafeInteger(item) ||
        item < min ||
        item > max
      )
        throw new Error(ERROR);
    } else if (Object.prototype.hasOwnProperty.call(NUMBER_BOUNDS, key)) {
      if (
        typeof item !== "number" ||
        !Number.isFinite(item) ||
        item <= 0 ||
        item > NUMBER_BOUNDS[key]
      )
        throw new Error(ERROR);
    } else if (key === "mode") {
      if (item !== "auto") throw new Error(ERROR);
    } else if (key === "summary_model") {
      if (
        typeof item !== "string" ||
        item.trim() !== item ||
        !/^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$/.test(item)
      )
        throw new Error(ERROR);
    } else {
      throw new Error(ERROR);
    }
    result[key] = item;
  }
  const config: GlobalContextConfig = result;
  const target = config.target_ratio ?? 0.6;
  const trigger = config.trigger_ratio ?? 0.8;
  const summary = config.summary_trigger_ratio ?? 0.95;
  if (!(target < trigger && trigger <= summary)) throw new Error(ERROR);
  const margin = config.safety_margin ?? 1024;
  if (
    config.context_window !== undefined &&
    config.output_reserve !== undefined &&
    config.context_window <= config.output_reserve + margin
  )
    throw new Error(ERROR);
  if (
    config.summary_context_window !== undefined &&
    config.summary_context_window <=
      (config.summary_max_tokens ?? 2048) + margin
  )
    throw new Error(ERROR);
  return config;
}

export function globalContextFromRuntime(
  value: string | undefined,
): GlobalContextConfig | undefined {
  if (value === undefined) return undefined;
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error(ERROR);
  }
  return normalizeGlobalContext(parsed);
}
