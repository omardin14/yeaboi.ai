import {
  formatCpu,
  formatMem,
  formatPct,
  formatUptime,
  heatClass,
  hostAppLabel,
  statusBadgeClass,
} from "@/lib/format";

test("format helpers guard NaN/Infinity rather than rendering garbage", () => {
  expect(formatPct(NaN)).toBe("—");
  expect(formatCpu(NaN)).toBe("—");
  expect(formatPct(Infinity)).toBe("—");
  expect(heatClass(NaN)).toContain("zinc");
});

test("formatMem scales bytes to MB/GB", () => {
  expect(formatMem(0)).toBe("—");
  expect(formatMem(524_288_000)).toBe("500 MB");
  expect(formatMem(2 * 1_073_741_824)).toBe("2.0 GB");
});

test("formatPct rounds a fraction and guards null", () => {
  expect(formatPct(null)).toBe("—");
  expect(formatPct(0.905)).toBe("91%");
  expect(formatPct(0)).toBe("0%");
});

test("formatCpu rounds and guards null", () => {
  expect(formatCpu(null)).toBe("—");
  expect(formatCpu(12.6)).toBe("13%");
});

test("formatUptime is compact", () => {
  expect(formatUptime(null)).toBe("—");
  expect(formatUptime(90)).toBe("1m");
  expect(formatUptime(3_660)).toBe("1h 1m");
  expect(formatUptime(90_000)).toBe("1d 1h");
});

test("heatClass escalates across all bands", () => {
  expect(heatClass(null)).toContain("zinc");
  expect(heatClass(0.1)).toContain("emerald");
  expect(heatClass(0.5)).toContain("yellow");
  expect(heatClass(0.75)).toContain("amber");
  expect(heatClass(0.95)).toContain("rose");
});

test("statusBadgeClass differs per status", () => {
  expect(statusBadgeClass("Busy")).toContain("emerald");
  expect(statusBadgeClass("Idle")).toContain("sky");
  expect(statusBadgeClass("Dead")).toContain("zinc");
  expect(statusBadgeClass("Unknown")).toContain("amber");
});

test("hostAppLabel handles the Other variant", () => {
  expect(hostAppLabel("Cli")).toBe("cli");
  expect(hostAppLabel("VsCode")).toBe("vscode");
  expect(hostAppLabel({ Other: "cursor" })).toBe("cursor");
});
