// Behaviour harness for key-manager/desktop/plugin.js.
//
// Loads the real plugin module with the Hermes SDK and React replaced by small
// stubs, renders the Manager element tree once (hooks are stubbed, so it is a
// plain function call), and drives the key switch through its real handlers.
// Prints one JSON report on stdout; tests/test_desktop_plugin_contract.py
// asserts on it.
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
const rowType = () => findAll(Manager(managerElement.props), (n) => typeof n.type === "function" && n.type.name === "KeyRow");

async function scenario(name, setup) {
  sdk.reset();
  setup();
  const rows = rowType();
  const landal = rows.find((row) => row.props.entry.slug === "landal");
  await landal.props.onSelect(landal.props.entry);
  return { name, calls: structuredClone(sdk.calls), notices: structuredClone(sdk.notices) };
}

const report = {
  registered: registered.map((item) => item.id),
  rows: rowType().map((row) => ({ slug: row.props.entry.slug, active: row.props.active })),
  scenarios: [
    await scenario("accepted", () => {}),
    await scenario("rejected", () => sdk.failRpc("Unknown model alias")),
    await scenario("deferred", () => sdk.rpcResult({ key: "model", value: "landal", deferred: true })),
    await scenario("no-session", () => sdk.setFocused(null)),
  ],
};
process.stdout.write(JSON.stringify(report));
