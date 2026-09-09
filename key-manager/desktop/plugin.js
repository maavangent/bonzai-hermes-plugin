import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  GlyphSpinner,
  Input,
  PALETTE_AREA,
  PANES_AREA,
  ScrollArea,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Separator,
  STATUSBAR_AREAS,
  StatusDot,
  atom,
  host,
  useQuery,
  useQueryClient,
  useValue,
} from "@hermes/plugin-sdk";
import { useEffect, useMemo, useRef, useState } from "react";
import { jsx, jsxs } from "react/jsx-runtime";

const PLUGIN_ID = "bonzai-key-manager";
const QUERY_KEY = [PLUGIN_ID, "credentials"];
const STRATEGY_KEY = [PLUGIN_ID, "strategy"];
const sessionStatus = atom({ provider: "", running: false, credential_binding: null });
const STRATEGIES = [
  ["fill_first", "Fill first"],
  ["round_robin", "Round robin"],
  ["least_used", "Least used"],
  ["random", "Random"],
];

const styles = {
  pane: {
    display: "flex",
    flexDirection: "column",
    height: "100%",
    minWidth: 0,
  },
  body: { display: "flex", flexDirection: "column", gap: 14, padding: 12 },
  section: { display: "flex", flexDirection: "column", gap: 8 },
  row: { display: "flex", alignItems: "center", gap: 8, minWidth: 0 },
  spread: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  muted: { color: "var(--ui-text-secondary)", fontSize: 12, lineHeight: 1.45 },
  tiny: { color: "var(--ui-text-quaternary)", fontSize: 11, lineHeight: 1.35 },
  card: {
    border: "1px solid var(--ui-stroke-secondary)",
    borderRadius: 6,
    display: "flex",
    flexDirection: "column",
    gap: 8,
    padding: 10,
  },
  grow: { flex: 1, minWidth: 0 },
  label: {
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    fontSize: 12,
    fontWeight: 600,
  },
  error: {
    color: "var(--ui-text-danger, var(--destructive))",
    fontSize: 12,
    lineHeight: 1.4,
  },
};

function messageOf(error) {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string") return error;
  if (error && typeof error === "object") {
    const candidate = error.detail ?? error.error ?? error.message;
    if (typeof candidate === "string") return candidate;
    if (candidate && typeof candidate.message === "string")
      return candidate.message;
  }
  return "The Bonzai key manager request failed.";
}

function unwrap(value) {
  if (!value || typeof value !== "object") return value;
  if ("data" in value && value.data != null) return value.data;
  if ("result" in value && value.result != null) return value.result;
  return value;
}

function credentialsFrom(value) {
  const data = unwrap(value);
  const list = Array.isArray(data)
    ? data
    : (data?.credentials ?? data?.items ?? data?.entries ?? []);
  return Array.isArray(list) ? list : [];
}

function credentialId(entry, index) {
  return String(entry.id ?? entry.credential_id ?? entry.key_id ?? index);
}

function credentialLabel(entry, index) {
  return String(
    entry.label ??
      entry.name ??
      entry.display_name ??
      `Bonzai key ${index + 1}`,
  );
}

function credentialSource(entry) {
  return String(entry.source ?? entry.origin ?? entry.kind ?? "manual");
}

function isManual(entry) {
  const source = credentialSource(entry).toLowerCase();
  if (entry.manual === true || entry.editable === true) return true;
  if (entry.removable === false || entry.renameable === false) return false;
  return !source.includes("env") && !source.includes("environment");
}

function stateOf(entry) {
  if (entry.disabled || entry.exhausted) return ["Unavailable", "bad"];
  if (
    entry.cooldown ||
    entry.cooldown_until ||
    entry.cooldown_remaining ||
    entry.status === "cooldown"
  )
    return ["Cooldown", "warn"];
  const normalized = String(entry.status ?? "").toLowerCase();
  if (normalized && !["available", "ok", "ready", "healthy"].includes(normalized)) {
    return [String(entry.status), "muted"];
  }
  return ["Ready", "good"];
}

function maskedHint(entry) {
  return (
    entry.masked ??
    entry.mask ??
    entry.preview ??
    entry.key_hint ??
    entry.api_key_hint ??
    null
  );
}

async function request(ctx, path, options) {
  try {
    return await ctx.rest(path, options);
  } catch (error) {
    throw new Error(messageOf(error));
  }
}

function useAction() {
  const [pending, setPending] = useState(null);
  const [error, setError] = useState(null);
  const run = async (name, action) => {
    setPending(name);
    setError(null);
    try {
      return await action();
    } catch (err) {
      setError(messageOf(err));
      throw err;
    } finally {
      setPending(null);
    }
  };
  return { pending, error, clearError: () => setError(null), run };
}

function BonzaiStatusLabel() {
  const session = useValue(sessionStatus);
  let label = "iO";
  if (session.alias) {
    label = session.alias;
  } else if (session.provider && session.provider !== "bonzai" && session.provider !== "custom") {
    label = session.provider;
  } else if (session.model) {
    label = session.model;
  }
  return jsxs("span", {
    style: { display: "inline-flex", alignItems: "center", gap: 5 },
    children: [jsx(StatusDot, { tone: "good" }), `Bonzai · ${label}`],
  });
}

function CredentialCard({ ctx, entry, index, busy, onChanged }) {
  const id = credentialId(entry, index);
  const label = credentialLabel(entry, index);
  const manual = isManual(entry);
  const canRename = manual && entry.renameable !== false;
  const canRemove = manual && entry.removable !== false;
  const [status, tone] = stateOf(entry);
  const [renaming, setRenaming] = useState(false);
  const [nextLabel, setNextLabel] = useState(label);
  const [confirmRemove, setConfirmRemove] = useState(false);

  useEffect(() => setNextLabel(label), [label]);

  const test = () =>
    onChanged(
      `test:${id}`,
      () => request(ctx, "/credentials/test-stored", { method: "POST", body: { id } }),
      "Credential test completed.",
    );
  const rename = async (event) => {
    event.preventDefault();
    const value = nextLabel.trim();
    if (!value || value === label) {
      setRenaming(false);
      return;
    }
    await onChanged(
      `rename:${id}`,
      () =>
        request(ctx, `/credentials/${encodeURIComponent(id)}`, {
          method: "PATCH",
          body: { label: value },
        }),
      "Credential renamed.",
    );
    setRenaming(false);
  };
  const remove = () =>
    onChanged(
      `remove:${id}`,
      () =>
        request(ctx, `/credentials/${encodeURIComponent(id)}`, {
          method: "DELETE",
        }),
      "Credential removed.",
    );

  const activate = async () => {
    const sid = host.state.activeSessionId.get();
    if (!sid) {
      host.notify({
        kind: "warning",
        message: "No active chat session selected.",
      });
      return;
    }
    try {
      let slug =
        label === "BONZAI_API_KEY"
          ? "io"
          : label
              .toLowerCase()
              .replace(/[\s_]+/g, "-")
              .replace(/[^a-z0-9-]/g, "");

      try {
        const res = await request(ctx, `/credentials/${encodeURIComponent(id)}/activate`, {
          method: "POST",
        });
        const data = unwrap(res);
        if (data?.slug) slug = data.slug;
      } catch {
        // Fallback to computed slug
      }

      const res = await host.request("slash.exec", {
        command: `/model ${slug}`,
        session_id: sid,
      });
      const output = unwrap(res)?.output || "";
      host.notify({
        kind: "success",
        message: output || `Switched session to /model ${slug}`,
      });
    } catch (err) {
      host.notify({
        kind: "error",
        message: `Could not switch model: ${messageOf(err)}`,
      });
    }
  };

  return jsxs("div", {
    style: styles.card,
    children: [
      jsxs("div", {
        style: styles.spread,
        children: [
          jsxs("div", {
            style: { ...styles.row, ...styles.grow },
            children: [
              jsx(StatusDot, { tone }),
              jsx("span", {
                style: styles.label,
                title: label,
                children: label,
              }),
            ],
          }),
          jsx(Badge, { variant: "outline", children: status }),
        ],
      }),
      jsxs("div", {
        style: styles.spread,
        children: [
          jsx("span", {
            style: styles.tiny,
            children:
              maskedHint(entry) ??
              (manual ? "Manual credential" : "Environment credential"),
          }),
          jsx("span", {
            style: styles.tiny,
            children: manual ? "Manual" : "Read only",
          }),
        ],
      }),
      renaming
        ? jsxs("form", {
            onSubmit: rename,
            style: styles.row,
            children: [
              jsx(Input, {
                autoFocus: true,
                "aria-label": "New credential label",
                onChange: (event) => setNextLabel(event.target.value),
                style: styles.grow,
                value: nextLabel,
              }),
              jsx(Button, {
                disabled: busy,
                size: "xs",
                type: "submit",
                children: "Save",
              }),
              jsx(Button, {
                onClick: () => setRenaming(false),
                size: "xs",
                type: "button",
                variant: "ghost",
                children: "Cancel",
              }),
            ],
          })
        : jsxs("div", {
            style: styles.row,
            children: [
              jsx(Button, {
                disabled: busy,
                onClick: activate,
                size: "xs",
                variant: "outline",
                children: "Use in Chat",
              }),
              jsx(Button, {
                disabled: busy,
                onClick: test,
                size: "xs",
                variant: "secondary",
                children: busy === `test:${id}` ? "Testing…" : "Test",
              }),
              canRename
                ? jsx(Button, {
                    disabled: busy,
                    onClick: () => setRenaming(true),
                    size: "xs",
                    variant: "ghost",
                    children: "Rename",
                  })
                : null,
              canRemove
                ? jsx(Button, {
                    disabled: busy,
                    onClick: () => setConfirmRemove(true),
                    size: "xs",
                    variant: "ghost",
                    children: "Remove",
                  })
                : null,
            ],
          }),
      jsx(ConfirmDialog, {
        confirmLabel: "Remove",
        description: `Remove “${label}” from the Bonzai credential pool? This cannot be undone.`,
        destructive: true,
        onClose: () => setConfirmRemove(false),
        onConfirm: remove,
        open: confirmRemove,
        title: "Remove credential?",
      }),
    ],
  });
}

function Manager({ ctx }) {
  const queryClient = useQueryClient();
  const labelRef = useRef(null);
  const [label, setLabel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [confirmReset, setConfirmReset] = useState(false);
  const action = useAction();
  const profile = useValue(host.state.profile);
  const activeSessionId = useValue(host.state.activeSessionId);
  const sessionInfo = useValue(sessionStatus);

  const credentials = useQuery({
    queryKey: [...QUERY_KEY, profile],
    queryFn: () => request(ctx, "/credentials"),
    refetchInterval: 15000,
  });
  const strategy = useQuery({
    queryKey: [...STRATEGY_KEY, profile],
    queryFn: () => request(ctx, "/strategy"),
  });
  const entries = useMemo(
    () => credentialsFrom(credentials.data),
    [credentials.data],
  );
  const strategyData = unwrap(strategy.data);
  const strategyValue = String(
    typeof strategyData === "string"
      ? strategyData
      : (strategyData?.strategy ?? strategyData?.value ?? "fill_first"),
  );

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: QUERY_KEY }),
      queryClient.invalidateQueries({ queryKey: STRATEGY_KEY }),
    ]);
  };

  const changed = async (name, operation, success) => {
    const result = await action.run(name, operation);
    await refresh();
    if (success) host.notify({ kind: "success", message: success });
    return result;
  };

  const add = async (event) => {
    event.preventDefault();
    const cleanLabel = label.trim();
    const cleanKey = apiKey.trim();
    if (!cleanLabel || !cleanKey) return;
    await changed(
      "add",
      () =>
        request(ctx, "/credentials", {
          method: "POST",
          body: { label: cleanLabel, api_key: cleanKey },
        }),
      "Bonzai credential added.",
    );
    setLabel("");
    setApiKey("");
    labelRef.current?.focus();
  };

  const changeStrategy = (value) =>
    changed(
      "strategy",
      () =>
        request(ctx, "/strategy", { method: "PUT", body: { strategy: value } }),
      "Rotation strategy updated.",
    );
  const reset = () =>
    changed(
      "reset",
      () => request(ctx, "/credentials/reset", { method: "POST" }),
      "Credential cooldowns reset.",
    );
  const selectedCredentialId = String(
    sessionInfo.credential_binding?.credential_id ?? "automatic",
  );
  const changeSessionCredential = async (value) => {
    if (!activeSessionId) return;
    if (sessionInfo.running) {
      host.notify({
        kind: "warning",
        message: "Wait until the current turn finishes to switch API keys.",
      });
      return;
    }
    const entry = credentials.find(
      (c, idx) => credentialId(c, idx) === value,
    );
    const label = entry ? credentialLabel(entry, 0) : "";
    const slug =
      value === "automatic" || label === "BONZAI_API_KEY"
        ? "io"
        : label
            .toLowerCase()
            .replace(/[\s_]+/g, "-")
            .replace(/[^a-z0-9-]/g, "");

    await action.run(`session:${value}`, () =>
      host.request("slash.exec", {
        command: `/model ${slug}`,
        session_id: activeSessionId,
      }),
    );
    sessionStatus.set({
      ...sessionStatus.get(),
      credential_binding:
        value === "automatic"
          ? null
          : { provider: "bonzai", credential_id: value, mode: "strict" },
    });
    host.notify({
      kind: "success",
      message: `Switched session to /model ${slug}`,
    });
  };

  return jsx("div", {
    "data-bonzai-key-manager": "true",
    style: styles.pane,
    children: jsx(ScrollArea, {
      style: { flex: 1, minHeight: 0 },
      children: jsxs("div", {
        style: styles.body,
        children: [
          jsxs("section", {
            style: styles.section,
            children: [
              jsx("strong", {
                style: { fontSize: 13 },
                children: "This session",
              }),
              jsx("p", {
                style: styles.muted,
                children:
                  "Choose one Bonzai key for this session, or let Hermes rotate automatically. A pinned key fails closed and never falls back to another account.",
              }),
              jsxs(Select, {
                disabled:
                  !activeSessionId ||
                  sessionInfo.provider !== "bonzai" ||
                  sessionInfo.running ||
                  Boolean(action.pending),
                onValueChange: changeSessionCredential,
                value: selectedCredentialId,
                children: [
                  jsx(SelectTrigger, {
                    "aria-label": "Credential for this session",
                    children: jsx(SelectValue, {}),
                  }),
                  jsxs(SelectContent, {
                    children: [
                      jsx(SelectItem, {
                        value: "automatic",
                        children: "Automatic rotation",
                      }),
                      ...entries.map((entry, index) =>
                        jsx(
                          SelectItem,
                          {
                            value: credentialId(entry, index),
                            children: credentialLabel(entry, index),
                          },
                          credentialId(entry, index),
                        ),
                      ),
                    ],
                  }),
                ],
              }),
              sessionInfo.running
                ? jsx("p", {
                    style: styles.tiny,
                    children: "Wait until the current turn finishes to switch API keys.",
                  })
                : null,
            ],
          }),
          jsx(Separator, {}),
          jsxs("section", {
            style: styles.section,
            children: [
              jsxs("div", {
                style: styles.spread,
                children: [
                  jsx("strong", {
                    style: { fontSize: 13 },
                    children: "Automatic rotation",
                  }),
                  jsx(Button, {
                    disabled: credentials.isFetching,
                    onClick: () => refresh(),
                    size: "xs",
                    variant: "ghost",
                    children: credentials.isFetching
                      ? "Refreshing…"
                      : "Refresh",
                  }),
                ],
              }),
              jsx("p", {
                style: styles.muted,
                children:
                  "Automatic rotation applies whenever this session is not pinned to a specific key.",
              }),
              jsxs("div", {
                style: styles.row,
                children: [
                  jsxs(Select, {
                    disabled: action.pending === "strategy",
                    onValueChange: changeStrategy,
                    value: STRATEGIES.some(([value]) => value === strategyValue)
                      ? strategyValue
                      : "fill_first",
                    children: [
                      jsx(SelectTrigger, {
                        "aria-label": "Credential rotation strategy",
                        style: styles.grow,
                        children: jsx(SelectValue, {}),
                      }),
                      jsx(SelectContent, {
                        children: STRATEGIES.map(([value, text]) =>
                          jsx(SelectItem, { value, children: text }, value),
                        ),
                      }),
                    ],
                  }),
                  jsx(Button, {
                    disabled: Boolean(action.pending),
                    onClick: () => setConfirmReset(true),
                    size: "xs",
                    variant: "secondary",
                    children:
                      action.pending === "reset"
                        ? "Resetting…"
                        : "Reset cooldowns",
                  }),
                ],
              }),
            ],
          }),
          jsx(Separator, {}),
          jsxs("section", {
            style: styles.section,
            children: [
              jsx("strong", {
                style: { fontSize: 13 },
                children: "Add credential",
              }),
              jsx("p", {
                style: styles.tiny,
                children:
                  "Keys are sent directly to the local plugin backend and are never saved in browser storage.",
              }),
              jsxs("form", {
                onSubmit: add,
                style: styles.section,
                children: [
                  jsx(Input, {
                    "aria-label": "Credential label",
                    onChange: (event) => setLabel(event.target.value),
                    placeholder: "Label",
                    ref: labelRef,
                    value: label,
                  }),
                  jsx(Input, {
                    "aria-label": "Bonzai API key",
                    autoComplete: "new-password",
                    onChange: (event) => setApiKey(event.target.value),
                    placeholder: "Bonzai API key",
                    type: "password",
                    value: apiKey,
                  }),
                  jsx(Button, {
                    disabled:
                      Boolean(action.pending) ||
                      !label.trim() ||
                      !apiKey.trim(),
                    type: "submit",
                    children: action.pending === "add" ? "Adding…" : "Add key",
                  }),
                ],
              }),
            ],
          }),
          jsx(Separator, {}),
          jsxs("section", {
            style: styles.section,
            children: [
              jsxs("div", {
                style: styles.spread,
                children: [
                  jsx("strong", {
                    style: { fontSize: 13 },
                    children: "Credentials",
                  }),
                  jsx(Badge, {
                    variant: "muted",
                    children: String(entries.length),
                  }),
                ],
              }),
              action.error
                ? jsxs("div", {
                    role: "alert",
                    style: styles.spread,
                    children: [
                      jsx("span", {
                        style: styles.error,
                        children: action.error,
                      }),
                      jsx(Button, {
                        onClick: action.clearError,
                        size: "xs",
                        variant: "ghost",
                        children: "Dismiss",
                      }),
                    ],
                  })
                : null,
              credentials.isLoading
                ? jsx("div", {
                    style: {
                      display: "flex",
                      justifyContent: "center",
                      padding: 16,
                    },
                    children: jsx(GlyphSpinner, {}),
                  })
                : null,
              credentials.isError
                ? jsx(ErrorState, {
                    title: "Could not load credentials",
                    description: messageOf(credentials.error),
                    children: jsx(Button, {
                      onClick: () => credentials.refetch(),
                      size: "sm",
                      variant: "secondary",
                      children: "Try again",
                    }),
                  })
                : null,
              !credentials.isLoading &&
              !credentials.isError &&
              entries.length === 0
                ? jsx(EmptyState, {
                    description:
                      "Add a manual Bonzai API key above, or configure one in the environment.",
                    title: "No credentials found",
                  })
                : null,
              entries.map((entry, index) =>
                jsx(
                  CredentialCard,
                  {
                    busy: action.pending,
                    ctx,
                    entry,
                    index,
                    onChanged: changed,
                  },
                  credentialId(entry, index),
                ),
              ),
            ],
          }),
          jsx(ConfirmDialog, {
            confirmLabel: "Reset cooldowns",
            description:
              "Clear cooldown and exhaustion state for all Bonzai credentials? Keys that are still rate-limited may fail again.",
            onClose: () => setConfirmReset(false),
            onConfirm: reset,
            open: confirmReset,
            title: "Reset credential cooldowns?",
          }),
        ],
      }),
    }),
  });
}

function locateManager() {
  host.notify({
    kind: "info",
    message:
      "Open Bonzai Key Manager from the “Bonzai keys” menu in the status bar.",
  });
}

export default {
  id: PLUGIN_ID,
  name: "Bonzai Key Manager",
  description: "Manage Bonzai credentials and automatic rotation.",
  defaultEnabled: true,
  register(ctx) {
    const disposeProvider = host.onEvent("session.info", (event) => {
      const activeSessionId = host.state.activeSessionId.get();
      const eventSessionId = String(event?.session_id ?? "");
      if (eventSessionId && activeSessionId && eventSessionId !== activeSessionId) return;
      const payload = event?.payload ?? {};
      const provider = String(payload.provider ?? "").trim().toLowerCase();
      const model = String(payload.model ?? "").trim();
      const alias = String(payload.model_alias ?? "").trim();
      sessionStatus.set({
        provider,
        model,
        alias,
        running: Boolean(payload.running),
        credential_binding: payload.credential_binding ?? null,
      });
    });

    ctx.registerMany([
      {
        id: "status",
        area: STATUSBAR_AREAS.right,
        order: 82,
        data: {
          id: "bonzai-key-manager.status",
          label: jsx(BonzaiStatusLabel, {}),
          title: "Manage Bonzai credentials and client aliases",
          variant: "menu",
          menuAlign: "end",
          menuClassName: "w-[360px] p-0",
          menuContent: () => jsx(Manager, { ctx }),
        },
      },
      {
        id: "manager",
        area: PANES_AREA,
        title: "Bonzai Keys",
        data: { placement: "right", width: "340px" },
        render: () => jsx(Manager, { ctx }),
      },
      {
        id: "focus",
        area: PALETTE_AREA,
        data: {
          id: "bonzai-key-manager.focus",
          label: "Bonzai: Locate key manager",
          keywords: ["bonzai", "credentials", "keys", "rotation"],
          run: locateManager,
        },
      },
    ]);
    return () => {
      disposeProvider();
    };
  },
};
