// Behaviour harness for key-manager/desktop/plugin.js.
//
// Loads the real plugin module with Hermes SDK and React replaced by small
// stubs, renders Manager once, and invokes its real UI handlers.
import { register } from "node:module";
import { pathToFileURL } from "node:url";

const stubs = {
  "@hermes/plugin-sdk": "sdk-stub.mjs",
  react: "react-stub.mjs",
  "react/jsx-runtime": "jsx-stub.mjs",
};
const here = new URL(".", import.meta.url);
register(
  "data:text/javascript," +
    encodeURIComponent(`
      const map = ${JSON.stringify(Object.fromEntries(Object.entries(stubs).map(([k, v]) => [k, new URL(v, here).href])))};
      export async function resolve(specifier, context, next) {
        if (map[specifier]) return { url: map[specifier], shortCircuit: true };
        return next(specifier, context);
      }
    `),
);

const sdk = await import(new URL("sdk-stub.mjs", here).href);
const plugin = (await import(pathToFileURL(process.argv[2]).href)).default;

function findAll(node, predicate, out = []) {
  if (!node || typeof node !== "object") return out;
  if (Array.isArray(node)) {
    node.forEach((child) => findAll(child, predicate, out));
    return out;
  }
  if (predicate(node)) out.push(node);
  findAll(node.props?.children, predicate, out);
  return out;
}

const registered = [];
plugin.register({ registerMany: (items) => registered.push(...items), rest: (...args) => sdk.rest(...args) });
const menu = registered.find((item) => item.id === "status");
const managerElement = menu.data.menuContent();
const Manager = managerElement.type;

function renderManager() {
  const root = Manager(managerElement.props);
  const rows = findAll(root, (node) => typeof node.type === "function" && node.type.name === "KeyRow");
  return { root, rows };
}

async function scenario(name, setup, action) {
  sdk.reset();
  setup();
  const { root, rows } = renderManager();
  const landal = rows.find((row) => row.props.entry.slug === "landal");
  if (action) await action(root, landal);
  else await landal.props.onSelect({ slug: "landal", label: "Landal" });
  return { name, calls: structuredClone(sdk.calls), notices: structuredClone(sdk.notices) };
}

const scenarios = [
  await scenario("accepted", () => {}),
  await scenario("rejected", () => sdk.failRpc("Unknown model alias")),
  await scenario("deferred", () => sdk.rpcResult({ key: "model", value: "landal", deferred: true })),
  await scenario("no-session", () => sdk.setFocused(null)),
  await scenario("ambiguous-route", () => sdk.setRoutes([])),
  await scenario("foreign-owner", () => {
    sdk.setOwner({ connectionId: "remote", profile: "work" });
    sdk.setRoutes([{ connectionId: "remote", mode: "remote", profile: "work", targetProfile: "work" }]);
  }),
  await scenario("focus-changed-during-route-resolution", () => {}, async (_root, landal) => {
    const switching = landal.props.onSelect({ slug: "landal", label: "Landal" });
    await Promise.resolve();
    sdk.setFocused("chat-2");
    await switching;
  }),
  await scenario("focus-changed-during-rpc", () => sdk.setSwitchDelay(10), async (_root, landal) => {
    const switching = landal.props.onSelect({ slug: "landal", label: "Landal" });
    await Promise.resolve();
    await Promise.resolve();
    sdk.setFocused("chat-2");
    await switching;
  }),
];

sdk.reset();
const { root, rows } = renderManager();
process.stdout.write(JSON.stringify({
  registered: registered.map((item) => item.id),
  rows: rows.map((row) => ({ slug: row.props.entry.slug, active: row.props.active })),
  sessionAttributes: {
    runtime: root.props["data-runtime-session"],
    stored: root.props["data-stored-session"],
    owner: root.props["data-owner-connection"],
  },
  scenarios,
}));
