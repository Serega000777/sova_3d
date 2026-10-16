import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const sessionSource = await readFile(new URL("../src/lib/session.ts", import.meta.url), "utf8");
const standaloneSessionSource = sessionSource
  .replace(
    'import { type AccountTier, PhysicalAiClient } from "@physical-ai/contracts";',
    `type AccountTier = "free" | "pro";
     class PhysicalAiClient { constructor(_options: unknown) {} }`,
  )
  .replace(
    'import { useEffect, useMemo, useSyncExternalStore } from "react";',
    `const useEffect = (..._args: unknown[]) => undefined;
     const useMemo = (factory: () => unknown) => factory();
     const useSyncExternalStore = (..._args: unknown[]) => null;`,
  )
  .replace(
    'import { parseCachedSession, serializeCachedSession } from "./sessionCache";',
    `const parseCachedSession = (raw: string | null) => ({
       session: raw ? JSON.parse(raw).session : null,
       migrated: false,
     });
     const serializeCachedSession = (session: unknown) => JSON.stringify({ session });`,
  );
const compiledSession = ts.transpileModule(standaloneSessionSource, {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { handleUnauthorizedSession, saveSession } = await import(
  `data:text/javascript;base64,${Buffer.from(compiledSession).toString("base64")}`
);

test("unauthorized session handling clears storage and redirects to login", () => {
  const stored = new Map<string, string>();
  let redirect = "";
  const originalWindow = globalThis.window;
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key: string) => stored.get(key) ?? null,
        setItem: (key: string, value: string) => stored.set(key, value),
        removeItem: (key: string) => stored.delete(key),
      },
      location: {
        pathname: "/projects/project-1",
        assign: (path: string) => {
          redirect = path;
        },
      },
    },
  });

  try {
    const session = {
      baseUrl: "https://api.example.test",
      token: "expired-token",
      workspaceId: "workspace-1",
    };
    saveSession(session);

    handleUnauthorizedSession(session.token);

    assert.equal(stored.size, 0);
    assert.equal(redirect, "/login");
  } finally {
    Object.defineProperty(globalThis, "window", { configurable: true, value: originalWindow });
  }
});
