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
  host,
  useQuery,
  useQueryClient,
  useValue,
} from "@hermes/plugin-sdk";
import { useMemo, useRef, useState } from "react";
import { jsx, jsxs } from "react/jsx-runtime";

const PLUGIN_ID = "bonzai-key-manager";
const QUERY_KEY = [PLUGIN_ID, "credentials"];
const SESSIONS_QUERY_KEY = [PLUGIN_ID, "sessions"];

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

function credentialSlug(entry) {
  const raw = String(entry.label ?? entry.name ?? entry.display_name ?? "");
  if (raw === "BONZAI_API_KEY" || raw.toLowerCase() === "io" || raw.toLowerCase() === "default") {
    return "io";
  }
  return raw.toLowerCase().replace(/[\s_]+/g, "-").replace(/[^a-z0-9-]/g, "");
}

function isManual(entry) {
  const source = String(entry.source ?? "").toLowerCase();
  if (entry.manual === true) return true;
  if (entry.removable === false) return false;
  return !source.includes("env") && !source.includes("environment");
}

async function request(ctx, path, options) {
  try {
    return await ctx.rest(path, options);
  } catch (error) {
    throw new Error(messageOf(error));
  }
}

export function BonzaiStatusLabel({ ctx }) {
  const focusedSessionId = useValue(host.state.focusedSessionId);
  const profile = useValue(host.state.profile);

  const credentialsQuery = useQuery({
    queryKey: [...QUERY_KEY, profile],
    queryFn: () => request(ctx, "/credentials"),
  });
  const sessionsQuery = useQuery({
    queryKey: [...SESSIONS_QUERY_KEY, profile],
    queryFn: () => request(ctx, "/sessions"),
    refetchInterval: 5000,
  });

  const entries = useMemo(
    () => credentialsFrom(credentialsQuery.data),
    [credentialsQuery.data],
  );

  const sessionsData = unwrap(sessionsQuery.data);
  const sessionMap = (sessionsData && typeof sessionsData === "object" && sessionsData.sessions) || {};
  const activeSlug = (focusedSessionId && sessionMap[focusedSessionId]) || "io";

  let activeLabel = "iO (Default)";
  if (activeSlug !== "io") {
    const found = entries.find((e) => credentialSlug(e) === activeSlug);
    if (found) {
      activeLabel = credentialLabel(found, 0);
    } else {
      activeLabel = activeSlug;
    }
  }

  return jsxs("span", {
    style: { display: "inline-flex", alignItems: "center", gap: 5 },
    children: [
      jsx(StatusDot, { tone: "good" }),
      `Bonzai · ${activeLabel}`,
    ],
  });
}

function KeyRow({ ctx, entry, index, activeSlug, busy, onSelect, onRemoved }) {
  const id = credentialId(entry, index);
  const label = credentialLabel(entry, index);
  const slug = credentialSlug(entry);
  const active = slug === activeSlug;
  const manual = isManual(entry);
  const [hover, setHover] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);

  const masked = entry.masked || (manual ? "Manual client key" : "Default environment key");

  const remove = async (e) => {
    e?.stopPropagation?.();
    if (active) {
      setConfirmRemove(false);
      host.notify({
        kind: "warning",
        message: `Select another key in this chat before removing “${label}”.`,
      });
      return;
    }
    try {
      await request(ctx, `/credentials/${encodeURIComponent(id)}`, { method: "DELETE" });
      setConfirmRemove(false);
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
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    children: [
      jsxs("div", {
        style: { display: "flex", alignItems: "center", gap: 8, flex: 1, minWidth: 0, cursor: active ? "default" : "pointer" },
        onClick: () => !active && onSelect(entry, index),
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
        onClick: (e) => e.stopPropagation(),
        onPointerDown: (e) => e.stopPropagation(),
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
  const focusedSessionId = useValue(host.state.focusedSessionId);

  const [adding, setAdding] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const [newKey, setNewKey] = useState("");
  const [busy, setBusy] = useState(false);

  const credentials = useQuery({
    queryKey: [...QUERY_KEY, profile],
    queryFn: () => request(ctx, "/credentials"),
  });
  const sessionsQuery = useQuery({
    queryKey: [...SESSIONS_QUERY_KEY, profile],
    queryFn: () => request(ctx, "/sessions"),
    refetchInterval: 5000,
  });

  const entries = useMemo(
    () => credentialsFrom(credentials.data),
    [credentials.data],
  );

  const sessionsData = unwrap(sessionsQuery.data);
  const sessionMap = (sessionsData && typeof sessionsData === "object" && sessionsData.sessions) || {};
  const activeSlug = (focusedSessionId && sessionMap[focusedSessionId]) || "io";

  let activeLabel = "iO (Default)";
  if (activeSlug !== "io") {
    const found = entries.find((e) => credentialSlug(e) === activeSlug);
    if (found) {
      activeLabel = credentialLabel(found, 0);
    } else {
      activeLabel = activeSlug;
    }
  }

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: QUERY_KEY }),
      queryClient.invalidateQueries({ queryKey: SESSIONS_QUERY_KEY }),
    ]);
  };

  const switchKey = async (entry, index) => {
    if (!focusedSessionId) {
      host.notify({ kind: "warning", message: "No active chat session selected." });
      return;
    }
    setBusy(true);
    const id = credentialId(entry, index);
    const slug = credentialSlug(entry);
    const display = credentialLabel(entry, index);

    // Optimistically update session keys query cache
    queryClient.setQueryData([...SESSIONS_QUERY_KEY, profile], (old) => {
      const current = (old && typeof old === "object" && old.sessions) ? old.sessions : {};
      return { sessions: { ...current, [focusedSessionId]: slug } };
    });

    try {
      await request(ctx, `/sessions/${encodeURIComponent(focusedSessionId)}`, {
        method: "POST",
        body: { slug },
      });
    } catch {
      // Background save failed; continue with slash command
    }

    try {
      await host.request("slash.exec", {
        command: `/model ${slug}`,
        session_id: focusedSessionId,
      });

      host.notify({ kind: "success", message: `Switched this chat to ${display}` });
    } catch (err) {
      host.notify({ kind: "error", message: `Could not switch key: ${messageOf(err)}` });
    } finally {
      setBusy(false);
      refresh();
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
              jsxs("div", {
                style: styles.headerStatus,
                children: [
                  jsx(StatusDot, { tone: "good" }),
                  activeLabel,
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
                      activeSlug,
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
    ctx.registerMany([
      {
        id: "status",
        area: STATUSBAR_AREAS.right,
        order: 82,
        data: {
          id: "bonzai-key-manager.status",
          label: jsx(BonzaiStatusLabel, { ctx }),
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
  },
};
