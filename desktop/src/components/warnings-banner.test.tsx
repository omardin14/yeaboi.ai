import { render, screen } from "@testing-library/react";
import { WarningsBanner } from "@/components/warnings-banner";

test("renders nothing when there are no warnings", () => {
  const { container } = render(<WarningsBanner warnings={[]} />);
  expect(container).toBeEmptyDOMElement();
});

test("lists each warning when present", () => {
  render(
    <WarningsBanner
      warnings={["claude: cannot read stats-cache.json", "codex: cannot access state.sqlite"]}
    />,
  );
  expect(screen.getByText(/cannot read stats-cache.json/)).toBeInTheDocument();
  expect(screen.getByText(/cannot access state.sqlite/)).toBeInTheDocument();
});
