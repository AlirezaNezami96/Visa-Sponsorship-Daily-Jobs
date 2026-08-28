/**
 * Injectable environment accessor.
 *
 * Edge Functions read Deno.env; Vitest (Node) injects overrides via setEnvForTest.
 * All env access in shared logic goes through getEnv so tests never touch process.env.
 */

const overrides = new Map<string, string | undefined>();

export function getEnv(name: string): string | undefined {
  if (overrides.has(name)) {
    return overrides.get(name);
  }
  try {
    // @ts-ignore Deno global
    if (typeof Deno !== "undefined") return Deno.env.get(name);
  } catch {
    /* node without polyfill */
  }
  // @ts-ignore Node global
  if (typeof process !== "undefined") return process.env[name];
  return undefined;
}

/** Test-only: override an env value. Pass undefined to delete. */
export function setEnvForTest(name: string, value: string | undefined): void {
  if (value === undefined) overrides.delete(name);
  else overrides.set(name, value);
}

export function clearEnvOverrides(): void {
  overrides.clear();
}
