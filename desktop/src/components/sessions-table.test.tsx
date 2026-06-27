import { render, screen } from "@testing-library/react";
import { SessionsTable } from "@/components/sessions-table";
import type { Snapshot } from "@/lib/bindings/Snapshot";

const snapshot: Snapshot = {
  generated_at_ms: 0,
  sessions: [
    { id: "s1", project: "demo", status: "busy" },
    { id: "s2", project: "other", status: "idle" },
  ],
  warnings: [],
};

test("renders a row per session", () => {
  render(<SessionsTable snapshot={snapshot} />);
  expect(screen.getByText("demo")).toBeInTheDocument();
  expect(screen.getByText("s1")).toBeInTheDocument();
  expect(screen.getByText("other")).toBeInTheDocument();
});

test("shows a loading state for a null snapshot", () => {
  render(<SessionsTable snapshot={null} />);
  expect(screen.getByText(/loading/i)).toBeInTheDocument();
});

test("shows an empty state when there are no sessions", () => {
  render(
    <SessionsTable snapshot={{ ...snapshot, sessions: [] }} />,
  );
  expect(screen.getByText(/no active sessions/i)).toBeInTheDocument();
});
