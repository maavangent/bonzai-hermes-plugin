// Minimal @hermes/plugin-sdk stand-in: records every host/REST call.
const element = (name) => {
  const component = (props) => ({ type: name, props });
  Object.defineProperty(component, "name", { value: name });
  return component;
};

export const Badge = element("Badge");
export const Button = element("Button");
export const ConfirmDialog = element("ConfirmDialog");
export const EmptyState = element("EmptyState");
export const ErrorState = element("ErrorState");
export const GlyphSpinner = element("GlyphSpinner");
export const Input = element("Input");
export const ScrollArea = element("ScrollArea");
export const Separator = element("Separator");
export const StatusDot = element("StatusDot");
export const PALETTE_AREA = "palette";
export const PANES_AREA = "panes";
export const STATUSBAR_AREAS = { right: "statusbar.right" };

const CREDENTIALS = {
  credentials: [
    { id: "io", slug: "io", label: "iO (Default)", kind: "default", configured: true, removable: false },
    { id: "landal", slug: "landal", label: "Landal", kind: "client", configured: true, removable: true },
  ],
};

let state;
export let calls = [];
export let notices = [];

export function reset() {
  state = {
    focused: "chat-1",
    owner: { connectionId: "local", profile: "default" },
    storedId: "stored-chat-1",
    routes: [{ connectionId: "local", mode: "local", profile: "default", targetProfile: "default" }],
    rpcError: null,
    rpcResult: { key: "model", value: "landal" },
    routeLookupError: null,
    switchDelay: 0,
  };
  calls.length = 0;
  notices.length = 0;
}
reset();

export const setFocused = (id) => { state.focused = id; state.storedId = id ? `stored-${id}` : null; };
export const setOwner = (owner) => { state.owner = owner; };
export const setRoutes = (routes) => { state.routes = routes; };
export const setRouteLookupError = (message) => { state.routeLookupError = message; };
export const setSwitchDelay = (milliseconds) => { state.switchDelay = milliseconds; };
export const failRpc = (message) => { state.rpcError = message; };
export const rpcResult = (result) => { state.rpcResult = result; };
export const snapshot = () => ({ focused: state.focused, storedId: state.storedId, owner: state.owner });

const atom = (read) => ({ read, get: read });
export const host = {
  state: {
    focusedSessionId: atom(() => state.focused),
    focusedStoredSessionId: atom(() => state.storedId),
    focusedSessionOwner: atom(() => state.owner),
    connectionId: atom(() => "local"),
    profile: atom(() => state.owner?.profile ?? "default"),
  },
  notify: (notice) => notices.push(notice),
  profileRoutes: async () => {
    calls.push({ via: "routes" });
    if (state.routeLookupError) throw new Error(state.routeLookupError);
    return state.routes;
  },
  requestProfile: async (route, method, params) => {
    calls.push({ via: "profile-rpc", route, method, params });
    if (state.switchDelay) await new Promise((resolve) => setTimeout(resolve, state.switchDelay));
    if (state.rpcError) throw new Error(state.rpcError);
    return state.rpcResult;
  },
  request: async (method, params) => {
    calls.push({ via: "rpc", method, params });
    if (state.rpcError) throw new Error(state.rpcError);
    return state.rpcResult;
  },
};

export async function rest(path, options = {}) {
  calls.push({ via: "rest", path, method: options.method ?? "GET", body: options.body ?? null });
  if (path === "/credentials") return CREDENTIALS;
  if (path === "/sessions") return { sessions: {} };
  return {};
}
export const ctx = { rest };

export const useValue = (a) => a.read();
export const useQueryClient = () => ({ invalidateQueries: async () => {} });
export function useQuery({ queryKey }) {
  const data = queryKey[0] === "bonzai-key-manager" ? CREDENTIALS : { sessions: {} };
  return { data, isLoading: false, isError: false, isSuccess: true, error: null };
}
