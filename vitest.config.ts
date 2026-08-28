import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    globals: false,
    include: ["supabase/functions/**/*.test.ts"],
    typecheck: {
      enabled: false,
    },
  },
  resolve: {
    alias: {
      // The functions import @supabase/supabase-js via Deno's npm: specifier in
      // supabase-clients.ts; shared logic under test has no supabase import, so
      // we only need to ensure bare specifiers resolve for Node.
      "@supabase/supabase-js": "@supabase/supabase-js",
    },
  },
});
