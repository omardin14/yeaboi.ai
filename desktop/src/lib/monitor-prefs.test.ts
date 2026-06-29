import { renderHook, act } from "@testing-library/react";
import { useMonitorPrefs } from "@/lib/monitor-prefs";

beforeEach(() => localStorage.removeItem("yb-monitor-prefs"));

test("defaults: only Activity is open; the rest start collapsed", () => {
  const { result } = renderHook(() => useMonitorPrefs());
  expect(result.current.isCollapsed("activity")).toBe(false);
  expect(result.current.isCollapsed("resources")).toBe(true);
  expect(result.current.isCollapsed("context")).toBe(true);
});

test("toggling a section persists across a remount", () => {
  const first = renderHook(() => useMonitorPrefs());
  act(() => first.result.current.toggleSection("activity"));
  expect(first.result.current.isCollapsed("activity")).toBe(true);
  first.unmount();

  const second = renderHook(() => useMonitorPrefs());
  expect(second.result.current.isCollapsed("activity")).toBe(true);
});

test("hiding a metric persists", () => {
  const { result } = renderHook(() => useMonitorPrefs());
  expect(result.current.isHidden("pid")).toBe(false);
  act(() => result.current.toggleMetric("pid"));
  expect(result.current.isHidden("pid")).toBe(true);
});

test("a corrupt stored value falls back to defaults", () => {
  localStorage.setItem("yb-monitor-prefs", "{not json");
  const { result } = renderHook(() => useMonitorPrefs());
  expect(result.current.isCollapsed("resources")).toBe(true);
  expect(result.current.isHidden("cpu")).toBe(false);
});
