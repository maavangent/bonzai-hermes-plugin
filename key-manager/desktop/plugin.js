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
import { useMemo, useState } from "react";
import { jsx, jsxs } from "react/jsx-runtime";

const PLUGIN_ID = "bonzai-key-manager";
const QUERY_KEY = [PLUGIN_ID, "credentials"];
const SESSIONS_QUERY_KEY = [PLUGIN_ID, "sessions"];
const DEFAULT_SLUG = "io";
const DEFAULT_LABEL = "iO (Default)";

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
  hint: {
    fontSize: 11,
    color: "var(--ui-text-tertiary, var(--muted-foreground))",
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
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
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
  const list = unwrap(value)?.credentials;
  return Array.isArray(list) ? list.filter((entry) => entry && typeof entry.slug === "string") : [];
}

function sessionMapFrom(value) {
  const sessions = unwrap(value)?.sessions;
  return sessions && typeof sessions === "object" ? sessions : {};
}

async function request(ctx, path, options) {
  try {
    return await ctx.rest(path, options);
  } catch (error) {
    throw new Error(messageOf(error));
  }
}

function useKeyState(ctx) {
  const focusedSessionId = useValue(host.state.focusedSessionId);
  const profile = useValue(host.state.profile);
  const credentials = useQuery({
    queryKey: [...QUERY_KEY, profile],
    queryFn: () => request(ctx, "/credentials"),
  });
  const sessions = useQuery({
    queryKey: [...SESSIONS_QUERY_KEY, profile],
    queryFn: () => request(ctx, "/sessions"),
    refetchInterval: 5000,
  });
  const entries = useMemo(() => credentialsFrom(credentials.data), [credentials.data]);
  const activeSlug = (focusedSessionId && sessionMapFrom(sessions.data)[focusedSessionId]) || DEFAULT_SLUG;
  const activeEntry = entries.find((entry) => entry.slug === activeSlug);
  // A binding whose key was removed elsewhere must not look healthy.
  const missing = activeSlug !== DEFAULT_SLUG && credentials.isSuccess && !activeEntry;
  const activeLabel = activeEntry?.label ?? (activeSlug === DEFAULT_SLUG ? DEFAULT_LABEL : activeSlug);
  return { focusedSessionId, profile, credentials, entries, activeSlug, activeLabel, missing };
}

export function BonzaiStatusLabel({ ctx }) {
  const { activeLabel, missing } = useKeyState(ctx);
  return jsxs("span", {
    style: { display: "inline-flex", alignItems: "center", gap: 5 },
    children: [
      jsx(StatusDot, { tone: missing ? "warn" : "good" }),
      `Bonzai · ${activeLabel}`,
    ],
  });
}

function KeyRow({ ctx, entry, active, busy, onSelect, onRemoved }) {
  const [hover, setHover] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const selectable = !active && !busy && entry.configured;
  const detail = [entry.masked ?? "No key stored", entry.model].filter(Boolean).join(" · ");

  const remove = async () => {
    if (active) {
      setConfirmRemove(false);
      host.notify({ kind: "warning", message: `Select another key in this chat before removing “${entry.label}”.` });
      return;
    }
    try {
      await request(ctx, `/credentials/${encodeURIComponent(entry.slug)}`, { method: "DELETE" });
      setConfirmRemove(false);
      onRemoved();
      host.notify({ kind: "success", message: `Removed “${entry.label}”` });
    } catch (err) {
      host.notify({ kind: "error", message: `Could not remove key: ${messageOf(err)}` });
    }
  };

  return jsxs("div", {
    style: { ...styles.row, ...(active ? styles.rowActive : hover && selectable ? styles.rowHover : {}) },
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    children: [
      jsxs("div", {
        style: { display: "flex", alignItems: "center", gap: 8, flex: 1, minWidth: 0, cursor: selectable ? "pointer" : "default" },
        onClick: () => selectable && onSelect(entry),
        children: [
          jsx(StatusDot, { tone: active ? "good" : entry.configured ? "muted" : "warn" }),
          jsxs("div", {
            style: styles.keyInfo,
            children: [
              jsx("span", { style: styles.keyName, children: entry.label }),
              jsx("span", { style: styles.keySub, children: detail }),
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
                disabled: !selectable,
                onClick: () => onSelect(entry),
                children: "Use",
              }),
          entry.removable && !active
            ? jsx(Button, {
                size: "xs",
                variant: "ghost",
                disabled: busy,
                "aria-label": `Remove ${entry.label}`,
                onClick: () => setConfirmRemove(true),
                children: "✕",
              })
            : null,
        ],
      }),
      jsx(ConfirmDialog, {
        confirmLabel: "Remove",
        description: `Remove “${entry.label}”? Its key is deleted from this Hermes profile and chats using it fall back to iO.`,
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
  const { focusedSessionId, profile, credentials, entries, activeSlug, activeLabel, missing } = useKeyState(ctx);
  const [adding, setAdding] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const [newKey, setNewKey] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: QUERY_KEY }),
      queryClient.invalidateQueries({ queryKey: SESSIONS_QUERY_KEY }),
    ]);

  const switchKey = async (entry) => {
    const sessionId = focusedSessionId;
    if (!sessionId) {
      host.notify({ kind: "warning", message: "Open a chat first, then pick a key for it." });
      return;
    }
    setBusy(true);
    try {
      // The same RPC Desktop's model picker uses: it reports a failed switch
      // as an error and defers a switch made while a reply is streaming.
      const result = unwrap(await host.request("config.set", {
        session_id: sessionId,
        key: "model",
        value: `${entry.slug} --session`,
      }));
      if (result?.confirm_required) {
        host.notify({ kind: "warning", message: result.confirm_message || result.warning || "Confirm this model in the chat first." });
        return;
      }
      // Record the binding only after Hermes accepted the switch, so the
      // status bar never claims a key this chat is not using.
      await request(ctx, `/sessions/${encodeURIComponent(sessionId)}`, {
        method: "POST",
        body: { slug: entry.slug },
      });
      host.notify({
        kind: "success",
        message: result?.deferred
          ? `${entry.label} takes over after the current reply`
          : `This chat now uses ${entry.label}`,
      });
    } catch (err) {
      host.notify({ kind: "error", message: `Could not switch key: ${messageOf(err)}` });
    } finally {
      setBusy(false);
      refresh();
    }
  };

  const addAndUse = async (e) => {
    e.preventDefault();
    const label = newLabel.trim();
    const apiKey = newKey.trim();
    if (!label || !apiKey) return;
    setBusy(true);
    let created = null;
    try {
      created = unwrap(await request(ctx, "/credentials", {
        method: "POST",
        body: { label, api_key: apiKey },
      }))?.credential;
      setNewLabel("");
      setNewKey("");
      setAdding(false);
      await refresh();
    } catch (err) {
      host.notify({ kind: "error", message: `Could not add key: ${messageOf(err)}` });
    } finally {
      setBusy(false);
    }
    if (created && focusedSessionId) {
      await switchKey(created);
    } else if (created) {
      host.notify({ kind: "success", message: `Added client key “${created.label}”` });
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
          jsxs("div", {
            style: styles.headerBox,
            children: [
              jsx("span", { style: styles.headerTitle, children: "Active In This Chat" }),
              jsxs("div", {
                style: styles.headerStatus,
                children: [jsx(StatusDot, { tone: missing ? "warn" : "good" }), activeLabel],
              }),
              missing
                ? jsx("span", { style: styles.hint, children: "This key was removed. Pick another key for this chat." })
                : null,
            ],
          }),

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
              credentials.isSuccess && entries.length === 0
                ? jsx(EmptyState, { title: "No keys found", description: "Add a Bonzai client key below." })
                : null,
              jsx("div", {
                style: styles.list,
                children: entries.map((entry) =>
                  jsx(KeyRow, {
                    ctx,
                    entry,
                    active: entry.slug === activeSlug,
                    busy,
                    onSelect: switchKey,
                    onRemoved: refresh,
                  }, entry.slug),
                ),
              }),
            ],
          }),

          jsx(Separator, {}),

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
                  }),
                  jsx(Input, {
                    placeholder: "Bonzai API Key",
                    type: "password",
                    autoComplete: "off",
                    value: newKey,
                    onChange: (e) => setNewKey(e.target.value),
                  }),
                  jsx("span", { style: styles.hint, children: "Stored only in this profile's .env. Never used for iO work." }),
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
                        children: busy ? "Saving…" : focusedSessionId ? "Save & Use" : "Save",
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
