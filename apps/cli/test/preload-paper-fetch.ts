import { fixtureFetcher } from "./paper-fixtures.ts";

// A real non-TTY CLI process uses saved responses, with no production test flags.
globalThis.fetch = Object.assign(
  (input: string | URL | Request, init?: RequestInit) => fixtureFetcher(input instanceof Request ? input.url : String(input), init ?? {}),
  { preconnect: () => {} },
);
