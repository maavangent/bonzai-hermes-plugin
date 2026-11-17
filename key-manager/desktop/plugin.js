import {
  atom,
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
import * as sdk from "@hermes/plugin-sdk";
import { useEffect, useMemo, useState } from "react";
import { jsx, jsxs } from "react/jsx-runtime";

const PLUGIN_ID = "bonzai-key-manager";
const QUERY_KEY = [PLUGIN_ID, "credentials"];
const SESSIONS_QUERY_KEY = [PLUGIN_ID, "sessions"];
const DEFAULT_SLUG = "io";
const DEFAULT_LABEL = "iO (Default)";
const INFO_QUERY_KEY = [PLUGIN_ID, "owner-info"];
const pendingSelections = atom({});
const PENDING_STORAGE_KEY = "unverified-pending-switches";
function storePending(ctx, value) {
  // Labels/opaque aliases only; never persist keys. Write before updating UI.
  ctx.storage?.set(PENDING_STORAGE_KEY, value);
  pendingSelections.set(value);
}
const focusedBusy = () => host.state.busy?.get() !== false;
const waitForIdle = () => host.notify({ kind: "warning", message: "Wait until this chat is idle before switching client keys." });
const identityKey = (identity) => JSON.stringify([identity.owner?.connectionId, identity.owner?.profile, identity.runtimeId, identity.storedId]);

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
  const runtimeSessionId = useValue(host.state.focusedSessionId);
  const storedSessionId = useValue(host.state.focusedStoredSessionId);
  const sessionOwner = useValue(host.state.focusedSessionOwner);
  const profile = useValue(host.state.profile);
  const connectionId = useValue(host.state.connectionId);
  const ownerMatchesPluginScope = Boolean(
    sessionOwner && connectionId && sessionOwner.connectionId === connectionId && sessionOwner.profile === profile
  );
  const scopeKey = [connectionId ?? null, profile ?? null];
  const credentials = useQuery({
    queryKey: [...QUERY_KEY, ...scopeKey],
    queryFn: () => request(ctx, "/credentials"),
  });
  const sessions = useQuery({
    queryKey: [...SESSIONS_QUERY_KEY, ...scopeKey],
    queryFn: () => request(ctx, "/sessions"),
    refetchInterval: 5000,
    enabled: ownerMatchesPluginScope,
  });
  const entries = useMemo(() => credentialsFrom(credentials.data), [credentials.data]);
  const identity = { runtimeId: runtimeSessionId, storedId: storedSessionId, owner: sessionOwner };
  const key = identityKey(identity);
  const pending = useValue(pendingSelections)[key];
  const infoKey = [...INFO_QUERY_KEY, ...scopeKey, runtimeSessionId, storedSessionId];
  const client = useQueryClient();
  const infoQuery = useQuery({
    queryKey: infoKey,
    enabled: ownerMatchesPluginScope && Boolean(runtimeSessionId),
    refetchInterval: 10000,
    queryFn: async () => {
      const route = await requestOwnerRoute(sessionOwner, identity);
      if (!scopeMatches(identity) || !sameSessionIdentity(identity, getActiveSessionIdentity())) throw new Error("The focused chat changed.");
      const info = unwrap(await host.requestProfile(route, "session.info", { session_id: runtimeSessionId }));
      if (info?.stored_session_id && info.stored_session_id !== storedSessionId) throw new Error("Session info belongs to another stored chat.");
      return info;
    },
  });
  useEffect(() => {
    if (!ownerMatchesPluginScope || !runtimeSessionId) return;
    const listen = ctx.onEvent?.bind(ctx) ?? host.onEvent;
    return listen("session.info", (event) => {
      if (event.session_id !== runtimeSessionId ||
          (event.connectionId ?? host.state.connectionId.get()) !== sessionOwner.connectionId ||
          (event.profile ?? event.payload?.profile_name) !== sessionOwner.profile ||
          !scopeMatches(identity) || !sameSessionIdentity(identity, getActiveSessionIdentity())) return;
      // Partial session.info events contain queue/cwd changes, not a route projection.
      if (typeof event.payload?.model !== "string" ||
          (event.payload.stored_session_id && event.payload.stored_session_id !== storedSessionId)) return;
      client.setQueryData(infoKey, event.payload);
      // No alias identity in this schema: running/model changes cannot settle a
      // deferred credential selection. Keep it pending instead of guessing.
    });
  }, [key, ownerMatchesPluginScope]);
  const info = unwrap(infoQuery.data);
  const selectedSlug = ownerMatchesPluginScope && storedSessionId ? sessionMapFrom(sessions.data)[storedSessionId] : null;
  const missing = Boolean(selectedSlug && credentials.isSuccess && !entries.some(entry => entry.slug === selectedSlug));
  // Hermes 0.23.2 reports model/provider (and sometimes a masked credential hint),
  // not a credential alias/opaque ID. Never infer a billed client from /sessions.
  const inactive = info?.provider && !["bonzai", "custom"].includes(info.provider) &&
    !entries.some(entry => info.provider === `custom:bonzai-key-${entry.slug}`);
  const activeSlug = null;
  const selectedLabel = selectedSlug ? entries.find(entry => entry.slug === selectedSlug)?.label ?? selectedSlug : null;
  const activeLabel = !ownerMatchesPluginScope ? "Open the owning profile"
    : !runtimeSessionId ? "Open a chat"
    : pending ? `Pending · ${pending.label}`
    : inactive ? "Inactive"
    : selectedLabel ? `Selected · ${selectedLabel}`
    : info ? "Key unverified" : "Status unknown";
  return { storedSessionId, sessionOwner, ownerMatchesPluginScope, profile, connectionId, credentials, entries, activeSlug, activeLabel, selectedLabel, missing };
}

export function BonzaiStatusLabel({ ctx }) {
  const { activeLabel, missing } = useKeyState(ctx);
  return jsxs("span", {
    style: { display: "inline-flex", alignItems: "center", gap: 5 },
    children: [
      jsx(StatusDot, { tone: missing ? "warn" : "muted" }),
      `Bonzai · ${activeLabel}`,
    ],
  });
}

function KeyRow({ ctx, entry, active, busy, allowed, scope, onSelect, onRemoved }) {
  const [hover, setHover] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [label, setLabel] = useState(entry.label);
  const [working, setWorking] = useState(false);
  const guard = () => scopeMatches(getActiveSessionIdentity()) &&
    host.state.connectionId.get() === scope.connectionId && host.state.profile.get() === scope.profile;
  const selectable = allowed && !active && !busy && !working && entry.configured;
  useEffect(() => { setConfirmRemove(false); setRenaming(false); setLabel(entry.label); }, [scope.connectionId, scope.profile, allowed, entry.label]);
  const maintain = async (path, options) => {
    if (!guard()) return;
    setWorking(true);
    try {
      const result = unwrap(await request(ctx, path, options));
      if (!guard()) return;
      if (options.method === "PATCH") {
        setRenaming(false);
        await onRemoved();
        host.notify({ kind: "success", message: "Client name updated." });
      } else {
        host.notify({ kind: result?.ok ? "success" : "error", message: result?.ok ? `Key test passed for ${entry.label}.` : `Key test failed: ${result?.message || result?.error || "The key was not accepted."}` });
      }
    } catch (error) { host.notify({ kind: "error", message: messageOf(error) }); }
    finally { setWorking(false); }
  };
  const detail = entry.masked ?? "No key stored";

  const remove = async () => {
    if (!guard()) return;
    if (Object.values(pendingSelections.get()).some(selection => selection.slug === entry.slug && selection.connectionId === scope.connectionId && selection.profile === scope.profile)) {
      host.notify({ kind: "warning", message: "This key has an unverified pending switch. Do not remove it until its chats have switched to another key." });
      setConfirmRemove(false);
      return;
    }
    if (active) {
      setConfirmRemove(false);
      host.notify({ kind: "warning", message: `Select another key in this chat before removing “${entry.label}”.` });
      return;
    }
    try {
      await request(ctx, `/credentials/${encodeURIComponent(entry.slug)}`, { method: "DELETE" });
      setConfirmRemove(false);
      await onRemoved();
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
                onClick: () => { if (guard()) return onSelect(entry); },
                "aria-label": `Use ${entry.label}`,
                children: "Use",
              }),
          jsx(Button, { size: "xs", variant: "ghost", disabled: !allowed || busy || working || !entry.configured, "aria-label": `Test ${entry.label}`, onClick: () => maintain("/credentials/test-stored", { method: "POST", body: { id: entry.slug } }), children: "Test" }),
          entry.renameable ? jsx(Button, { size: "xs", variant: "ghost", disabled: !allowed || busy || working, "aria-label": `Rename ${entry.label}`, onClick: () => { if (guard()) setRenaming(true); }, children: "Rename" }) : null,
          entry.removable && !active
            ? jsx(Button, {
                size: "xs",
                variant: "ghost",
                disabled: !allowed || busy || working,
                "aria-label": `Remove ${entry.label}`,
                onClick: () => { if (guard()) setConfirmRemove(true); },
                children: "✕",
              })
            : null,
        ],
      }),
      renaming ? jsxs("div", { children: [
        jsx(Input, { "aria-label": `Client name for ${entry.label}`, value: label, onChange: e => setLabel(e.target.value) }),
        jsx(Button, { size: "xs", disabled: !allowed || working || !label.trim(), onClick: () => maintain(`/credentials/${encodeURIComponent(entry.slug)}`, { method: "PATCH", body: { label: label.trim() } }), children: "Save name" }),
        jsx(Button, { size: "xs", onClick: () => setRenaming(false), children: "Cancel rename" }),
      ] }) : null,
      jsx(ConfirmDialog, {
        confirmLabel: "Remove",
        description: `Remove “${entry.label}”? Its key is deleted from this Hermes profile. Removal is blocked while any chat has this key selected.`,
        destructive: true,
        onClose: () => setConfirmRemove(false),
        onConfirm: remove,
        open: confirmRemove,
        title: "Remove client key?",
      }),
    ],
  });
}

const scopeMatches = (identity) => Boolean(
  identity.owner && identity.owner.connectionId === host.state.connectionId.get() &&
  identity.owner.profile === host.state.profile.get()
);

const getActiveSessionIdentity = () => ({
  runtimeId: host.state.focusedSessionId.get(),
  storedId: host.state.focusedStoredSessionId.get(),
  owner: host.state.focusedSessionOwner.get(),
});

const sameSessionIdentity = (left, right) =>
  left.runtimeId === right.runtimeId &&
  left.storedId === right.storedId &&
  left.owner?.connectionId === right.owner?.connectionId &&
  left.owner?.profile === right.owner?.profile;

async function requestOwnerRoute(owner, identity) {
  if (!owner || typeof host.profileRoutes !== "function" || typeof host.requestProfile !== "function") {
    throw new Error("The focused chat owner cannot be resolved on this Hermes Desktop version.");
  }
  let routes;
  try {
    routes = await host.profileRoutes();
  } catch (err) {
    if (!sameSessionIdentity(identity, getActiveSessionIdentity())) {
      throw new Error("The focused chat changed before the key switch. Try again.");
    }
    throw err;
  }
  const matches = (Array.isArray(routes) ? routes : []).filter((route) =>
    route?.connectionId === owner.connectionId && route?.targetProfile === owner.profile
  );
  if (matches.length !== 1) throw new Error("The focused chat owner route is missing or ambiguous.");
  return matches[0];
}

async function setKeyForFocusedSession(ctx, entry, expectedIdentity, onConfirmation, confirmToken, confirmedPayload) {
  const initialIdentity = expectedIdentity ?? getActiveSessionIdentity();
  if (!scopeMatches(initialIdentity) || !sameSessionIdentity(initialIdentity, getActiveSessionIdentity())) {
    host.notify({ kind: "warning", message: "Switch to the profile that owns this chat to manage its keys." });
    return;
  }
  if (!initialIdentity.runtimeId || !initialIdentity.storedId || !initialIdentity.owner) {
    host.notify({ kind: "warning", message: "Open a chat first, then pick a key for it." });
    return;
  }
  if (focusedBusy()) { waitForIdle(); return; }
  try {
    const route = await requestOwnerRoute(initialIdentity.owner, initialIdentity);
    if (!scopeMatches(initialIdentity) || !sameSessionIdentity(initialIdentity, getActiveSessionIdentity())) {
      throw new Error("The focused chat or profile changed before the key switch. Try again.");
    }
    if (focusedBusy()) { waitForIdle(); return; }
    let payload = confirmedPayload;
    if (!payload) {
      const info = unwrap(await host.requestProfile(route, "session.info", { session_id: initialIdentity.runtimeId }));
      if (info?.stored_session_id && info.stored_session_id !== initialIdentity.storedId) throw new Error("Session info belongs to another stored chat.");
      if (!scopeMatches(initialIdentity) || !sameSessionIdentity(initialIdentity, getActiveSessionIdentity())) throw new Error("The focused chat changed before preparing the key switch.");
      payload = unwrap(await request(ctx, `/credentials/${encodeURIComponent(entry.slug)}/route`, {
        method: "POST", body: { model: typeof info?.model === "string" && info.model ? info.model : null },
      }))?.payload;
      if (!payload?.model || !payload?.provider) throw new Error("This backend cannot prepare a model-preserving key switch.");
    }
    if (!scopeMatches(initialIdentity) || !sameSessionIdentity(initialIdentity, getActiveSessionIdentity())) throw new Error("The focused chat changed before the key switch.");
    if (focusedBusy()) { waitForIdle(); return; }
    const result = unwrap(await host.requestProfile(route, "session.model", {
      session_id: initialIdentity.runtimeId,
      payload,
      ...(confirmToken ? { confirm: confirmToken } : {}),
    }));
    if (result?.confirm_required) {
      if (onConfirmation && typeof result.confirm === "string") {
        onConfirmation({ entry, payload, identity: initialIdentity, token: result.confirm, message: result.confirm_message || result.warning || "Confirm this model switch." });
      } else {
        host.notify({ kind: "warning", message: result.confirm_message || result.warning || "Confirm this model in the chat first." });
      }
      return;
    }
    if (!sameSessionIdentity(initialIdentity, getActiveSessionIdentity())) {
      throw new Error("The focused chat changed during the key switch. The selection was not recorded.");
    }
    if (!scopeMatches(initialIdentity)) throw new Error("The profile changed during the key switch.");
    if (result?.deferred) {
      storePending(ctx, { ...pendingSelections.get(), [identityKey(initialIdentity)]: { slug: entry.slug, label: entry.label, deferred: true, connectionId: initialIdentity.owner.connectionId, profile: initialIdentity.owner.profile } });
    } else {
      await request(ctx, `/sessions/${encodeURIComponent(initialIdentity.storedId)}`, {
        method: "POST",
        body: { slug: entry.slug },
      });
      const next = { ...pendingSelections.get() };
      delete next[identityKey(initialIdentity)];
      storePending(ctx, next);
    }
    host.notify({
      kind: "info",
      message: result?.deferred
        ? `Hermes unexpectedly deferred ${entry.label}. Wait until idle, then select a key again to resolve this unverified pending switch.`
        : `Key switch accepted; the active billing key is not verified by this Hermes version.`,
    });
  } catch (err) {
    host.notify({ kind: "error", message: `Could not switch key: ${messageOf(err)}` });
  }
}

function Manager({ ctx }) {
  const queryClient = useQueryClient();
  const { storedSessionId, sessionOwner, ownerMatchesPluginScope, profile, connectionId, credentials, entries, activeSlug, activeLabel, selectedLabel, missing } = useKeyState(ctx);
  const scopedQueryKey = (prefix) => [...prefix, connectionId ?? null, profile ?? null];
  const activeIdentity = () => ({
    runtimeId: host.state.focusedSessionId.get(),
    storedId: host.state.focusedStoredSessionId.get(),
    owner: host.state.focusedSessionOwner.get(),
  });
  const sameIdentity = (left, right) =>
    left.runtimeId === right.runtimeId &&
    left.storedId === right.storedId &&
    left.owner?.connectionId === right.owner?.connectionId &&
    left.owner?.profile === right.owner?.profile;

  const [adding, setAdding] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const [newKey, setNewKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmation, setConfirmation] = useState(null);
  const confirmationSessionId = useValue(host.state.focusedSessionId);
  useEffect(() => { setConfirmation(null); }, [confirmationSessionId, connectionId, profile]);
  const chatBusy = useValue(host.state.busy);
  useEffect(() => {
    setNewKey("");
    setNewLabel("");
    setAdding(false);
  }, [connectionId, profile]);

  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: scopedQueryKey(QUERY_KEY) }),
      queryClient.invalidateQueries({ queryKey: scopedQueryKey(SESSIONS_QUERY_KEY) }),
      queryClient.invalidateQueries({ queryKey: scopedQueryKey(INFO_QUERY_KEY) }),
    ]);

  const switchKey = async (entry, identity, confirmToken, confirmedPayload) => {
    setBusy(true);
    try {
      await setKeyForFocusedSession(ctx, entry, identity, setConfirmation, confirmToken, confirmedPayload);
    } finally {
      setBusy(false);
      refresh();
    }
  };

  const addAndUse = async (e) => {
    e.preventDefault();
    const initialIdentity = getActiveSessionIdentity();
    if (!scopeMatches(initialIdentity) || host.state.connectionId.get() !== connectionId || host.state.profile.get() !== profile) return;
    if (initialIdentity.runtimeId && focusedBusy()) { waitForIdle(); return; }
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
    if (created && initialIdentity.runtimeId && scopeMatches(initialIdentity) && sameSessionIdentity(initialIdentity, getActiveSessionIdentity())) {
      await switchKey(created, initialIdentity);
    } else if (created) {
      host.notify({ kind: "success", message: `Added client key “${created.label}”` });
    }
  };

  return jsx("div", {
    "data-bonzai-key-manager": "true",
    "data-testid": "bonzai-key-manager",
    "data-runtime-session": activeIdentity().runtimeId || "",
    "data-stored-session": activeIdentity().storedId || "",
    "data-owner-connection": activeIdentity().owner?.connectionId || "",
    style: styles.pane,
    children: jsx(ScrollArea, {
      style: { flex: 1, minHeight: 0 },
      children: jsxs("div", {
        style: styles.body,
        children: [
          jsx(ConfirmDialog, {
            open: Boolean(confirmation),
            title: "Switch model for this chat?",
            description: confirmation?.message || "",
            confirmLabel: "Switch",
            onClose: () => setConfirmation(null),
            onConfirm: async () => {
              const requested = confirmation;
              setConfirmation(null);
              if (requested) await switchKey(requested.entry, requested.identity, requested.token, requested.payload);
            },
          }),
          jsxs("div", {
            style: styles.headerBox,
            children: [
              jsx("span", { style: styles.headerTitle, children: "This Chat" }),
              jsxs("div", {
                style: styles.headerStatus,
                children: [jsx(StatusDot, { tone: missing ? "warn" : "muted" }), activeLabel],
              }),
              chatBusy ? jsx("span", { style: styles.hint, children: "Wait until this chat is idle before switching client keys." }) : null,
              selectedLabel ? jsx("span", { style: styles.hint, children: `Selected · ${selectedLabel} (not verified active)` }) : null,
              jsx("span", { style: styles.hint, children: "Hermes may fall back to another provider. This panel cannot verify the billing credential." }),
              missing
                ? jsx("span", { style: styles.hint, children: "This key was removed. Pick another key for this chat." })
                : !ownerMatchesPluginScope
                  ? jsx("span", { style: styles.hint, children: "Switch to the profile that owns this chat to manage its keys." })
                  : null,
            ],
          }),

          jsxs("div", {
            style: { display: "flex", flexDirection: "column", gap: 6 },
            children: [
              jsx("span", { style: styles.headerTitle, children: "Available Keys" }),
              !ownerMatchesPluginScope || credentials.isLoading
                ? jsx("div", { style: { padding: 12, display: "flex", justifyContent: "center" }, children: jsx(GlyphSpinner, {}) })
                : null,
              !ownerMatchesPluginScope || credentials.isError
                ? jsx(ErrorState, {
                    title: ownerMatchesPluginScope ? "Could not load keys" : "Wrong profile",
                    description: ownerMatchesPluginScope
                      ? messageOf(credentials.error)
                      : "Switch to the profile that owns this chat to manage its keys.",
                    children: jsx(Button, { size: "xs", onClick: refresh, children: "Retry" }),
                  })
                : null,
              ownerMatchesPluginScope && credentials.isSuccess && entries.length === 0
                ? jsx(EmptyState, { title: "No keys found", description: "Add a Bonzai client key below." })
                : null,
              jsx("div", {
                style: styles.list,
                children: entries.map((entry) =>
                  jsx(KeyRow, {
                    ctx,
                    entry,
                    active: entry.slug === activeSlug,
                    busy: busy || chatBusy,
                    allowed: ownerMatchesPluginScope,
                    scope: { connectionId, profile },
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
                    "aria-label": "Client name",
                    placeholder: "Client name (e.g. Landal, Heineken)",
                    value: newLabel,
                    onChange: (e) => setNewLabel(e.target.value),
                  }),
                  jsx(Input, {
                    placeholder: "Bonzai API Key",
                    type: "password",
                    "aria-label": "Bonzai API key",
                    autoComplete: "off",
                    value: newKey,
                    onChange: (e) => setNewKey(e.target.value),
                  }),
                  jsx("span", { style: styles.hint, children: "Stored in this profile. Session selection does not disable Hermes provider fallback." }),
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
                        disabled: !ownerMatchesPluginScope || busy || chatBusy || !newLabel.trim() || !newKey.trim(),
                        children: busy ? "Saving…" : activeIdentity().runtimeId ? "Save & Use" : "Save",
                      }),
                    ],
                  }),
                ],
              })
            : jsx(Button, {
                size: "sm",
                variant: "outline",
                disabled: !ownerMatchesPluginScope || busy,
                onClick: () => { if (scopeMatches(getActiveSessionIdentity())) setAdding(true); },
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
    const saved = ctx.storage?.get(PENDING_STORAGE_KEY, {});
    if (saved && typeof saved === "object" && !Array.isArray(saved)) pendingSelections.set(saved);
    const settingsAvailable = typeof ctx.registerSettingsPage === "function" && typeof sdk.pluginSettingsHref === "function";
    if (settingsAvailable) ctx.registerSettingsPage({ id: "keys", title: "Bonzai Keys", render: () => jsx(Manager, { ctx }) });
    // Routes predate the settings seam; namespace import keeps older-host loading safe.
    if (!settingsAvailable && sdk.ROUTES_AREA) ctx.registerMany([{ id: "keys-page", area: sdk.ROUTES_AREA, data: { path: "/bonzai-keys" }, render: () => jsx(Manager, { ctx }) }]);
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
            if (settingsAvailable) { host.navigate(sdk.pluginSettingsHref(`${PLUGIN_ID}:keys`)); return; }
            if (sdk.ROUTES_AREA) { host.navigate("/bonzai-keys"); return; }
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
