export const useState = (initial) => [typeof initial === "function" ? initial() : initial, () => {}];
export const useMemo = (factory) => factory();
export const useRef = (initial) => ({ current: initial });
