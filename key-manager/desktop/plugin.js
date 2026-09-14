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
  Separator,
  STATUSBAR_AREAS,
  StatusDot,
  atom,
  host,
  useQuery,
  useQueryClient,
  useValue,
} from "@hermes/plugin-sdk";
import { useMemo, useRef, useState } from "react";
import { jsx, jsxs } from "react/jsx-runtime";

const PLUGIN_ID = "bonzai-key-manager";
const QUERY_KEY = [PLUGIN_ID, "credentials"];
const sessionStatus = atom({ provider: "", model: "", alias: "", running: false });

const styles = {
  pane: {
    display: "flex",
    flexDirection: "column",
    height: "100%",
    minWidth: 0,
    userSelect: "none",
  },
  body: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
    padding: 12,
  },
  headerBox: {
    padding: "8px 10px",
    borderRadius: 8,
    border: "1px solid var(--ui-stroke-secondary, rgba(125,125,125,0.15))",
    backgroundColor: "var(--ui-surface-subtle, rgba(125,125,125,0.04))",
    display: "flex",
    flexDirection: "column",
    gap: 4,
  },
  headerTitle: {
    fontSize: 11,
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "0.04em",
    color: "var(--ui-text-tertiary, var(--muted-foreground))",
  },
  headerStatus: {
    fontSize: 12,
    fontWeight: 600,
    display: "flex",
    alignItems: "center",
    gap: 6,
    color: "var(--foreground)",
  },
  list: {
    display: "flex",
    flexDirection: "column",
    gap: 4,
  },
  row: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "8px 10px",
    borderRadius: 8,
    border: "1px solid transparent",
    cursor: "pointer",
    transition: "background-color 0.12s ease, border-color 0.12s ease",
  },
  rowActive: {
    backgroundColor: "var(--ui-surface-selected, rgba(0, 100, 255, 0.08))",
    borderColor: "var(--ui-stroke-active, rgba(0, 100, 255, 0.25))",
  },
  rowHover: {
    backgroundColor: "var(--ui-surface-hover, rgba(125, 125, 125, 0.07))",
  },
  keyInfo: {
    display: "flex",
    flexDirection: "column",
    gap: 2,
    minWidth: 0,
    flex: 1,
  },
  keyName: {
    fontSize: 12,
    fontWeight: 600,
    color: "var(--foreground)",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  keySub: {
    fontSize: 11,
    color: "var(--ui-text-tertiary, var(--muted-foreground))",
    fontFamily: "var(--font-mono, monospace)",
  },
  addBox: {
    padding: 10,
    borderRadius: 8,
    border: "1px solid var(--ui-stroke-secondary, rgba(125,125,125,0.18))",
    backgroundColor: "var(--card)",
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  actions: {
    display: "flex",
    alignItems: "center",
    gap: 6,
  },
};

function messageOf(error) {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string") return error;
  if (error && typeof error === "object") {
    const candidate = error.detail ?? error.error ?? error.message;
    if (typeof candidate === "string") return candidate;
    if (candidate && typeof candidate.message === "string") return candidate.message;
  }
  return "The request failed.";
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
  const raw = String(entry.label ?? entry.name ?? entry.display_name ?? `Key ${index + 1}`);
  if (raw === "BONZAI_API_KEY") return "iO (Default)";
  return raw;
}

function isManual(entry) {
  const source = String(entry.source ?? "").toLowerCase();
  if (entry.manual === true) return true;
  if (entry.removable === false) return false;
  return !source.includes("env") && !source.includes("environment");
}

function isEntryActive(entry, index, session) {
  const rawLabel = String(entry.label ?? entry.name ?? "");
  const slug = (rawLabel === "BONZAI_API_KEY" || rawLabel.toLowerCase() === "io" || rawLabel.toLowerCase() === "default")
    ? "io"
    : rawLabel.toLowerCase().replace(/[\s_]+/g, "-").replace(/[^a-z0-9-]/g, "");

  const currentAlias = (session.alias || "").toLowerCase();
  const currentProvider = (session.provider || "").toLowerCase();

  if (currentAlias) {
    return currentAlias === slug;
  }
  if (currentProvider === "bonzai" || currentProvider === "custom") {
    return slug === "io";
  }
  return false;
}

async function request(ctx, path, options) {
  try {
    return await ctx.rest(path, options);
  } catch (error) {
    throw new Error(messageOf(error));
  }
}

export function BonzaiStatusLabel() {
  const session = useValue(sessionStatus);
  const isBonzai = session.provider === "bonzai" || session.provider === "custom" || Boolean(session.alias);

  if (!isBonzai && session.provider) {
    return jsxs("span", {
      style: { display: "inline-flex", alignItems: "center", gap: 5, opacity: 0.75 },
      children: [
        jsx(StatusDot, { tone: "muted" }),
        "Bonzai · Inactive",
      ],
    });
  }

  let activeLabel = "iO (Default)";
  if (session.alias) {
    activeLabel = session.alias === "io" ? "iO (Default)" : session.alias;
  } else if (session.model) {
    activeLabel = session.model;
  }

  return jsxs("span", {
    style: { display: "inline-flex", alignItems: "center", gap: 5 },
    children: [
      jsx(StatusDot, { tone: "good" }),
      `Bonzai · ${activeLabel}`,
    ],
  });
}

function KeyRow({ ctx, entry, index, session, busy, onSelect, onRemoved }) {
  const id = credentialId(entry, index);
  const label = credentialLabel(entry, index);
  const active = isEntryActive(entry, index, session);
  const manual = isManual(entry);
  const [hover, setHover] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);

  const masked = entry.masked || (manual ? "Manual client key" : "Default environment key");

  const remove = async (e) => {
    e.stopPropagation();
    try {
      await request(ctx, `/credentials/${encodeURIComponent(id)}`, { method: "DELETE" });
      onRemoved();
      host.notify({ kind: "success", message: `Removed “${label}”` });
    } catch (err) {
      host.notify({ kind: "error", message: `Could not remove key: ${messageOf(err)}` });
    }
  };

  const rowStyle = {
    ...styles.row,
    ...(active ? styles.rowActive : (hover ? styles.rowHover : {})),
  };

  return jsxs("div", {
    style: rowStyle,
    onClick: () => !active && onSelect(entry, index),
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    children: [
      jsxs("div", {
        style: { display: "flex", alignItems: "center", gap: 8, flex: 1, minWidth: 0 },
        children: [
          jsx(StatusDot, { tone: active ? "good" : "muted" }),
          jsxs("div", {
            style: styles.keyInfo,
            children: [
              jsx("span", { style: styles.keyName, children: label }),
              jsx("span", { style: styles.keySub, children: masked }),
            ],
          }),
        ],
      }),
      jsxs("div", {
        style: styles.actions,
        children: [
          active
            ? jsx(Badge, { variant: "default", children: "Active in chat" })
            : jsx(Button, {
                size: "xs",
                variant: "ghost",
                disabled: busy,
                onClick: (e) => {
                  e.stopPropagation();
                  onSelect(entry, index);
                },
                children: "Use",
              }),
          manual && !active
            ? jsx(Button, {
                size: "xs",
                variant: "ghost",
                disabled: busy,
                onClick: (e) => {
                  e.stopPropagation();
                  setConfirmRemove(true);
                },
                children: "✕",
              })
            : null,
        ],
      }),
      jsx(ConfirmDialog, {
        confirmLabel: "Remove",
        description: `Remove “${label}” from Bonzai keys? This will remove the client alias.`,
        destructive: true,
        onClose: () => setConfirmRemove(false),
        onConfirm: remove,
        open: confirmRemove,
        title: "Remove client key?",
      }),
    ],
  });
}

function Manager({ ctx }) {
  const queryClient = useQueryClient();
  const nameInputRef = useRef(null);
  const profile = useValue(host.state.profile);
  const activeSessionId = useValue(host.state.activeSessionId);
  const session = useValue(sessionStatus);

  const [adding, setAdding] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const [newKey, setNewKey] = useState("");
  const [busy, setBusy] = useState(false);

  const credentials = useQuery({
    queryKey: [...QUERY_KEY, profile],
    queryFn: () => request(ctx, "/credentials"),
    refetchInterval: 15000,
  });

  const entries = useMemo(
    () => credentialsFrom(credentials.data),
    [credentials.data],
  );

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: QUERY_KEY });
  };

  const switchKey = async (entry, index) => {
    if (!activeSessionId) {
      host.notify({ kind: "warning", message: "No active chat session selected." });
      return;
    }
    setBusy(true);
    const id = credentialId(entry, index);
    const rawLabel = String(entry.label ?? entry.name ?? "");
    let slug = (rawLabel === "BONZAI_API_KEY" || rawLabel.toLowerCase() === "io" || rawLabel.toLowerCase() === "default")
      ? "io"
      : rawLabel.toLowerCase().replace(/[\s_]+/g, "-").replace(/[^a-z0-9-]/g, "");

    try {
      const res = await request(ctx, `/credentials/${encodeURIComponent(id)}/activate`, {
        method: "POST",
      });
      const data = unwrap(res);
      if (data?.slug) slug = data.slug;
    } catch {
      // Fallback to computed slug
    }

    try {
      await host.request("slash.exec", {
        command: `/model ${slug}`,
        session_id: activeSessionId,
      });

      // Optimistic update
      sessionStatus.set({
        ...sessionStatus.get(),
        provider: "bonzai",
        alias: slug === "io" ? "io" : slug,
      });

      const display = credentialLabel(entry, index);
      host.notify({ kind: "success", message: `Switched this chat to ${display}` });
    } catch (err) {
      host.notify({ kind: "error", message: `Could not switch key: ${messageOf(err)}` });
    } finally {
      setBusy(false);
    }
  };

  const addAndUse = async (e) => {
    e.preventDefault();
    const cleanLabel = newLabel.trim();
    const cleanKey = newKey.trim();
    if (!cleanLabel || !cleanKey) return;

    setBusy(true);
    try {
      const res = await request(ctx, "/credentials", {
        method: "POST",
        body: { label: cleanLabel, api_key: cleanKey },
      });
      const data = unwrap(res);
      const created = data?.credential;

      await refresh();
      setNewLabel("");
      setNewKey("");
      setAdding(false);

      if (created) {
        await switchKey(created, 0);
      } else {
        host.notify({ kind: "success", message: `Added client key “${cleanLabel}”` });
      }
    } catch (err) {
      host.notify({ kind: "error", message: `Could not add key: ${messageOf(err)}` });
    } finally {
      setBusy(false);
    }
  };

  const isBonzai = session.provider === "bonzai" || session.provider === "custom" || Boolean(session.alias);
  const activeLabel = session.alias
    ? (session.alias === "io" ? "iO (Default)" : session.alias)
    : (isBonzai ? "iO (Default)" : null);

  return jsx("div", {
    "data-bonzai-key-manager": "true",
    style: styles.pane,
    children: jsx(ScrollArea, {
      style: { flex: 1, minHeight: 0 },
      children: jsxs("div", {
        style: styles.body,
        children: [
          // Active chat status banner
          jsxs("div", {
            style: styles.headerBox,
            children: [
              jsx("span", { style: styles.headerTitle, children: "Active In This Chat" }),
              activeLabel
                ? jsxs("div", {
                    style: styles.headerStatus,
                    children: [
                      jsx(StatusDot, { tone: "good" }),
                      activeLabel,
                    ],
                  })
                : jsxs("div", {
                    style: { ...styles.headerStatus, color: "var(--ui-text-warning, #d97706)" },
                    children: [
                      jsx(StatusDot, { tone: "warn" }),
                      "Bonzai is not active in this chat",
                    ],
                  }),
            ],
          }),

          // Keys list
          jsxs("div", {
            style: { display: "flex", flexDirection: "column", gap: 6 },
            children: [
              jsx("span", { style: styles.headerTitle, children: "Available Keys" }),
              credentials.isLoading
                ? jsx("div", { style: { padding: 12, display: "flex", justifyContent: "center" }, children: jsx(GlyphSpinner, {}) })
                : null,
              credentials.isError
                ? jsx(ErrorState, {
                    title: "Could not load keys",
                    description: messageOf(credentials.error),
                    children: jsx(Button, { size: "xs", onClick: refresh, children: "Retry" }),
                  })
                : null,
              !credentials.isLoading && !credentials.isError && entries.length === 0
                ? jsx(EmptyState, { title: "No keys found", description: "Add a Bonzai client key below." })
                : null,
              jsxs("div", {
                style: styles.list,
                children: entries.map((entry, index) =>
                  jsx(
                    KeyRow,
                    {
                      ctx,
                      entry,
                      index,
                      session,
                      busy,
                      onSelect: switchKey,
                      onRemoved: refresh,
                    },
                    credentialId(entry, index),
                  ),
                ),
              }),
            ],
          }),

          jsx(Separator, {}),

          // Add client key form or trigger button
          adding
            ? jsxs("form", {
                onSubmit: addAndUse,
                style: styles.addBox,
                children: [
                  jsx("span", { style: { fontSize: 12, fontWeight: 600 }, children: "Add Client Key" }),
                  jsx(Input, {
                    autoFocus: true,
                    placeholder: "Client name (e.g. Landal, Heineken)",
                    value: newLabel,
                    onChange: (e) => setNewLabel(e.target.value),
                    ref: nameInputRef,
                  }),
                  jsx(Input, {
                    placeholder: "Bonzai API Key",
                    type: "password",
                    value: newKey,
                    onChange: (e) => setNewKey(e.target.value),
                  }),
                  jsxs("div", {
                    style: { display: "flex", gap: 6, justifyContent: "flex-end", marginTop: 4 },
                    children: [
                      jsx(Button, {
                        size: "xs",
                        type: "button",
                        variant: "ghost",
                        onClick: () => {
                          setAdding(false);
                          setNewLabel("");
                          setNewKey("");
                        },
                        children: "Cancel",
                      }),
                      jsx(Button, {
                        size: "xs",
                        type: "submit",
                        disabled: busy || !newLabel.trim() || !newKey.trim(),
                        children: busy ? "Saving…" : "Save & Use",
                      }),
                    ],
                  }),
                ],
              })
            : jsx(Button, {
                size: "sm",
                variant: "outline",
                onClick: () => setAdding(true),
                style: { width: "100%", justifyContent: "center" },
                children: "+ Add Client Key",
              }),
        ],
      }),
    }),
  });
}

export default {
  id: PLUGIN_ID,
  name: "Bonzai Key Manager",
  description: "Select and manage client API keys per chat session.",
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
          title: "Bonzai Keys & Client Selection",
          variant: "menu",
          menuAlign: "end",
          menuClassName: "w-[320px] p-0",
          menuContent: () => jsx(Manager, { ctx }),
        },
      },
      {
        id: "manager",
        area: PANES_AREA,
        title: "Bonzai Keys",
        data: { placement: "right", width: "320px" },
        render: () => jsx(Manager, { ctx }),
      },
      {
        id: "focus",
        area: PALETTE_AREA,
        data: {
          id: "bonzai-key-manager.focus",
          label: "Bonzai: Select client key",
          keywords: ["bonzai", "client", "keys", "landal", "io"],
          run: () => {
            host.notify({
              kind: "info",
              message: "Click the Bonzai menu in the bottom-right status bar to switch client keys.",
            });
          },
        },
      },
    ]);

    return () => {
      disposeProvider();
    };
  },
};
