// Tiny classname joiner — avoids pulling in `clsx` for a 6-line helper.
// Falsy entries are dropped so `cx("a", cond && "b")` reads cleanly.
export type ClassValue = string | false | null | undefined;

export function cx(...parts: ClassValue[]): string {
  return parts.filter(Boolean).join(" ");
}
